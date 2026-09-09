#!/usr/bin/env python3
"""Train king-conditioned H64 output heads on the certified Gestalt teacher corpus.

The expensive 768x64 first layer is frozen exactly at the proven V15 b050 weights.  We learn
small additive white-king and black-king output deltas, then fold them into a 64-entry table of
8x8 king-bucket output heads for deployment.  Inference still performs exactly 64 SCReLU/output
products; it merely chooses which 64-weight output row to use from the two king squares.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import chess
import numpy as np

INPUTS = 768
HIDDEN = 64
KING_BUCKETS = 8
HEADS = KING_BUCKETS * KING_BUCKETS
QA = 255
QB = 64
CP_SCALE = 400
DEPLOY_DEN = 12
TARGET_CLIP_CP = 1200


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--teacher', type=Path, required=True)
    p.add_argument('--engine-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--alpha', type=float, required=True)
    p.add_argument('--epochs', type=int, default=90)
    p.add_argument('--batch-size', type=int, default=384)
    p.add_argument('--learning-rate', type=float, default=0.003)
    p.add_argument('--ridge', type=float, default=0.0015)
    p.add_argument('--seed', type=int, default=20260909)
    return p.parse_args()


def feature_index(piece: chess.Piece, square: int) -> int:
    return (0 if piece.color == chess.WHITE else 384) + (piece.piece_type - 1) * 64 + square


def king_bucket(square: int, white: bool) -> int:
    rank = square >> 3
    file = square & 7
    if not white:
        rank = 7 - rank
    return (rank >> 1) * 2 + (1 if file >= 4 else 0)


def trunc_div(values: np.ndarray, divisor: int) -> np.ndarray:
    v = values.astype(np.int64, copy=False)
    return np.where(v >= 0, v // divisor, -((-v) // divisor))


def load_engine(engine: Path):
    sys.path.insert(0, str(engine.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state_v13_only
    return encode_position, _build_eval_state_into, _evaluate_state_v13_only, int(EVAL_WIDTH)


def exact_hidden(x: np.ndarray, qw0: np.ndarray, qb0: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    accum = x.astype(np.int32) @ qw0.astype(np.int32) + qb0.astype(np.int32)
    clipped = np.clip(accum, 0, QA).astype(np.int64)
    h = np.square(clipped.astype(np.float32) / float(QA))
    return clipped, h


def exact_single_head_cp(clipped: np.ndarray, qw1: np.ndarray, qb1: int) -> np.ndarray:
    raw = np.sum(clipped * clipped * qw1.astype(np.int64)[None, :], axis=1, dtype=np.int64)
    scaled = trunc_div(raw, QA) + int(qb1)
    return trunc_div(scaled * CP_SCALE, QA * QB).astype(np.int32)


def exact_bucketed_cp(
    clipped: np.ndarray,
    pair: np.ndarray,
    qheads: np.ndarray,
    qbias: np.ndarray,
) -> np.ndarray:
    selected = qheads[pair].astype(np.int64)
    raw = np.sum(clipped * clipped * selected, axis=1, dtype=np.int64)
    scaled = trunc_div(raw, QA) + qbias[pair].astype(np.int64)
    return trunc_div(scaled * CP_SCALE, QA * QB).astype(np.int32)


class Adam:
    def __init__(self, arrays: list[np.ndarray], lr: float) -> None:
        self.lr = lr
        self.m = [np.zeros_like(a, dtype=np.float32) for a in arrays]
        self.v = [np.zeros_like(a, dtype=np.float32) for a in arrays]
        self.t = 0

    def step(self, arrays: list[np.ndarray], grads: list[np.ndarray]) -> None:
        self.t += 1
        b1, b2 = 0.9, 0.999
        c1, c2 = 1.0 - b1**self.t, 1.0 - b2**self.t
        for i, (a, g) in enumerate(zip(arrays, grads)):
            self.m[i] = b1 * self.m[i] + (1.0 - b1) * g
            self.v[i] = b2 * self.v[i] + (1.0 - b2) * np.square(g)
            a -= self.lr * (self.m[i] / c1) / (np.sqrt(self.v[i] / c2) + 1e-8)


def main() -> int:
    a = parse_args()
    if not (0.0 < a.alpha <= 1.0):
        raise SystemExit('alpha must be in (0,1]')
    a.output_dir.mkdir(parents=True, exist_ok=True)

    model_path = a.engine_dir / 'experiments' / 'v14_student_h64.npz'
    with np.load(model_path) as z:
        qw0 = z['feature_weights'].astype(np.int16)
        qb0 = z['feature_bias'].astype(np.int16)
        qw1 = z['output_weights'].astype(np.int16)
        qb1_arr = z['output_bias'].astype(np.int32).reshape(-1)
    if qw0.shape != (INPUTS, HIDDEN) or qb0.shape != (HIDDEN,) or qw1.shape != (HIDDEN,) or qb1_arr.size != 1:
        raise SystemExit(f'unexpected baseline model shapes {qw0.shape} {qb0.shape} {qw1.shape} {qb1_arr.shape}')
    qb1 = int(qb1_arr[0])

    rows=[]
    for line in a.teacher.read_text().splitlines():
        if not line.strip():
            continue
        r=json.loads(line)
        if r.get('teacher_mate') is None and abs(int(r['teacher_cp'])) <= 5000:
            rows.append(r)
    if not rows:
        raise SystemExit('no usable teacher rows')

    encode_position, build_state, v13_eval, eval_width = load_engine(a.engine_dir)
    n=len(rows)
    x=np.zeros((n,INPUTS),dtype=np.float32)
    teacher=np.empty(n,dtype=np.float32)
    v13=np.empty(n,dtype=np.float32)
    sign=np.empty(n,dtype=np.float32)
    wb=np.empty(n,dtype=np.int16)
    bb=np.empty(n,dtype=np.int16)
    split=np.empty(n,dtype=np.int8)
    split_map={'train':0,'validation':1,'holdout':2}

    for i,r in enumerate(rows):
        board=chess.Board(r['fen'])
        for sq,piece in board.piece_map().items():
            x[i,feature_index(piece,sq)]=1.0
        wk=board.king(chess.WHITE); bk=board.king(chess.BLACK)
        if wk is None or bk is None:
            raise SystemExit('teacher row missing king')
        wb[i]=king_bucket(wk,True); bb[i]=king_bucket(bk,False)
        enc=encode_position(board)
        state=np.empty(eval_width,dtype=np.int32)
        build_state(enc.board,state)
        v13[i]=int(v13_eval(enc.side,state))
        teacher[i]=int(r['teacher_cp'])
        sign[i]=1.0 if board.turn==chess.WHITE else -1.0
        split[i]=split_map[str(r['split'])]

    clipped,h=exact_hidden(x,qw0,qb0)
    old_raw_white=exact_single_head_cp(clipped,qw1,qb1).astype(np.float32)
    old_deployed_stm=v13 + sign * trunc_div(old_raw_white.astype(np.int64),DEPLOY_DEN).astype(np.float32)
    delta=np.clip(teacher-old_deployed_stm,-TARGET_CLIP_CP,TARGET_CLIP_CP)
    desired_stm=old_deployed_stm + a.alpha*delta
    y=sign*(desired_stm-v13)*DEPLOY_DEN/CP_SCALE

    base_w=qw1.astype(np.float32)/float(QB)
    base_b=float(qb1)/float(QA*QB)
    base_pred=h@base_w + base_b

    # Factorized king conditioning: shared baseline + white bucket delta + black bucket delta.
    dw=np.zeros((KING_BUCKETS,HIDDEN),dtype=np.float32)
    db=np.zeros((KING_BUCKETS,HIDDEN),dtype=np.float32)
    bw=np.zeros(KING_BUCKETS,dtype=np.float32)
    bblack=np.zeros(KING_BUCKETS,dtype=np.float32)
    arrays=[dw,db,bw,bblack]
    opt=Adam(arrays,a.learning_rate)
    rng=np.random.default_rng(a.seed+int(round(a.alpha*1000)))
    train_idx=np.flatnonzero(split==0); val_idx=np.flatnonzero(split==1); hold_idx=np.flatnonzero(split==2)
    best=None; best_rmse=float('inf'); history=[]

    def predict(ii: np.ndarray) -> np.ndarray:
        return (
            base_pred[ii]
            + np.sum(h[ii]*dw[wb[ii]],axis=1)
            + np.sum(h[ii]*db[bb[ii]],axis=1)
            + bw[wb[ii]] + bblack[bb[ii]]
        )

    for epoch in range(1,a.epochs+1):
        order=rng.permutation(train_idx)
        for start in range(0,len(order),a.batch_size):
            ii=order[start:start+a.batch_size]
            pred=predict(ii)
            err=pred-y[ii]
            gp=np.clip(err,-0.5,0.5).astype(np.float32)/max(1,len(ii))
            gdw=a.ridge*dw; gdb=a.ridge*db; gbw=a.ridge*bw; gbb=a.ridge*bblack
            # Eight buckets makes explicit grouped accumulation inexpensive and deterministic.
            for k in range(KING_BUCKETS):
                mask=(wb[ii]==k)
                if np.any(mask):
                    gdw[k] += h[ii[mask]].T @ gp[mask]
                    gbw[k] += float(np.sum(gp[mask]))
                mask=(bb[ii]==k)
                if np.any(mask):
                    gdb[k] += h[ii[mask]].T @ gp[mask]
                    gbb[k] += float(np.sum(gp[mask]))
            opt.step(arrays,[gdw,gdb,gbw,gbb])

        vp=predict(val_idx)
        rmse=float(np.sqrt(np.mean(np.square(vp-y[val_idx],dtype=np.float64))))
        history.append({'epoch':epoch,'validation_target_rmse_norm':rmse})
        if epoch==1 or epoch%10==0:
            print(json.dumps(history[-1]),flush=True)
        if rmse<best_rmse:
            best_rmse=rmse; best=[z.copy() for z in arrays]

    if best is None:
        raise AssertionError('no checkpoint')
    dw[:],db[:],bw[:],bblack[:]=best

    qheads=np.empty((HEADS,HIDDEN),dtype=np.int16)
    qbias=np.empty(HEADS,dtype=np.int32)
    for w in range(KING_BUCKETS):
        for b in range(KING_BUCKETS):
            pair=w*KING_BUCKETS+b
            head=base_w+dw[w]+db[b]
            bias=base_b+bw[w]+bblack[b]
            qheads[pair]=np.clip(np.rint(head*QB),-32768,32767).astype(np.int16)
            qbias[pair]=np.int32(np.clip(np.rint(bias*QA*QB),-(2**31),2**31-1))

    pair=(wb.astype(np.int32)*KING_BUCKETS+bb.astype(np.int32)).astype(np.int32)
    raw_cp=exact_bucketed_cp(clipped,pair,qheads,qbias).astype(np.float32)
    deployed_stm=v13 + sign*trunc_div(raw_cp.astype(np.int64),DEPLOY_DEN).astype(np.float32)

    def metrics(ii: np.ndarray) -> dict[str,float|int]:
        return {
            'records':int(len(ii)),
            'teacher_rmse_old_cp':float(np.sqrt(np.mean(np.square(teacher[ii]-old_deployed_stm[ii],dtype=np.float64)))),
            'teacher_rmse_new_cp':float(np.sqrt(np.mean(np.square(teacher[ii]-deployed_stm[ii],dtype=np.float64)))),
            'mean_abs_delta_from_old_cp':float(np.mean(np.abs(deployed_stm[ii]-old_deployed_stm[ii]))),
        }

    metadata={
        'schema':1,
        'architecture':'absolute768-h64-screlu-factorized-8x8-king-conditioned-output-heads-residual-on-v13',
        'alpha':a.alpha,
        'deploy_denominator':DEPLOY_DEN,
        'best_validation_target_rmse_norm':best_rmse,
        'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest(),
        'baseline_model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
        'metrics':{'train':metrics(train_idx),'validation':metrics(val_idx),'holdout':metrics(hold_idx)},
        'white_bucket_counts':[int(np.sum(wb==k)) for k in range(KING_BUCKETS)],
        'black_bucket_counts':[int(np.sum(bb==k)) for k in range(KING_BUCKETS)],
        'history':history,
    }
    np.savez_compressed(
        a.output_dir/'student-h64-king-output-heads.npz',
        feature_weights=qw0,
        feature_bias=qb0,
        output_weights=qheads,
        output_bias=qbias,
    )
    (a.output_dir/'training-metadata.json').write_text(json.dumps(metadata,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in metadata.items() if k!='history'},indent=2,sort_keys=True))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
