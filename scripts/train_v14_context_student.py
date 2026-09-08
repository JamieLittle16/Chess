#!/usr/bin/env python3
"""Train a king-context sparse single-accumulator V14 replacement student.

Features are 9 king-zone contexts x absolute768 piece-square rows.  The network is intentionally
small and runtime-shaped: one H64/H96 SCReLU accumulator and one scalar output.  It learns the full
Stockfish19 - classical correction, so a successful model can replace rather than stack on V13's
legacy residual.  Model selection uses validation RMSE only; holdout is untouched until final report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import chess
import numpy as np

BASE_FEATURES = 768
CONTEXTS = 9
FEATURES = BASE_FEATURES * CONTEXTS
MAX_ACTIVE = 32
QA = 255
QB = 64
CP_SCALE = 400
TARGET_CLIP_CP = 1800


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--teacher', type=Path, required=True)
    p.add_argument('--engine-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--hidden', type=int, choices=(64,96), default=64)
    p.add_argument('--epochs', type=int, default=40)
    p.add_argument('--batch-size', type=int, default=512)
    p.add_argument('--learning-rate', type=float, default=0.002)
    p.add_argument('--weight-decay', type=float, default=0.00002)
    p.add_argument('--seed', type=int, default=20260908)
    return p.parse_args()


def king_zone(square: int) -> int:
    f = chess.square_file(square)
    return 0 if f <= 2 else (1 if f <= 4 else 2)


def context_of(board: chess.Board) -> int:
    wk, bk = board.king(chess.WHITE), board.king(chess.BLACK)
    if wk is None or bk is None:
        raise ValueError('position lacks king')
    return king_zone(wk) * 3 + king_zone(bk)


def base_feature(piece: chess.Piece, square: int) -> int:
    return (0 if piece.color == chess.WHITE else 384) + (piece.piece_type - 1) * 64 + square


def load_classical_api(engine_dir: Path):
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state_classical
    return encode_position, _build_eval_state_into, _evaluate_state_classical, int(EVAL_WIDTH)


def build_dataset(path: Path, engine_dir: Path) -> dict[str, np.ndarray]:
    encode_position, build_state, evaluate_classical, eval_width = load_classical_api(engine_dir)
    rows: list[dict[str, Any]] = []
    with path.open(encoding='utf-8') as h:
        for line in h:
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get('teacher_mate') is not None or abs(int(r['teacher_cp'])) > 5000:
                continue
            rows.append(r)
    if not rows:
        raise ValueError('no usable teacher rows')

    ids = np.full((len(rows), MAX_ACTIVE), -1, dtype=np.int32)
    counts = np.empty(len(rows), dtype=np.int8)
    teacher = np.empty(len(rows), dtype=np.float32)
    baseline = np.empty(len(rows), dtype=np.float32)
    target = np.empty(len(rows), dtype=np.float32)
    side_sign = np.empty(len(rows), dtype=np.float32)
    codes = np.empty(len(rows), dtype=np.int8)
    split_map = {'train':0, 'validation':1, 'holdout':2}

    for i, r in enumerate(rows):
        board = chess.Board(r['fen'])
        context = context_of(board)
        active = [context * BASE_FEATURES + base_feature(piece, square)
                  for square, piece in board.piece_map().items()]
        if len(active) > MAX_ACTIVE:
            raise AssertionError(len(active))
        ids[i, :len(active)] = active
        counts[i] = len(active)
        e = encode_position(board)
        state = np.empty(eval_width, dtype=np.int32)
        build_state(e.board, state)
        base = int(evaluate_classical(e.side, state))
        sf = int(r['teacher_cp'])
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        residual_stm = max(-TARGET_CLIP_CP, min(TARGET_CLIP_CP, sf - base))
        teacher[i], baseline[i], side_sign[i] = sf, base, sign
        target[i] = sign * residual_stm / CP_SCALE
        split = str(r['split'])
        if split not in split_map:
            raise ValueError(split)
        codes[i] = split_map[split]
    return {'ids':ids,'counts':counts,'teacher':teacher,'baseline':baseline,
            'target':target,'side_sign':side_sign,'codes':codes}


def sparse_hidden(ids: np.ndarray, counts: np.ndarray, w0: np.ndarray, b0: np.ndarray) -> np.ndarray:
    out = np.broadcast_to(b0, (len(ids), len(b0))).copy()
    for slot in range(ids.shape[1]):
        mask = counts > slot
        if np.any(mask):
            out[mask] += w0[ids[mask, slot]]
    return out


def forward(data: dict[str,np.ndarray], w0: np.ndarray, b0: np.ndarray,
            w1: np.ndarray, b1: np.ndarray) -> np.ndarray:
    z = sparse_hidden(data['ids'], data['counts'], w0, b0)
    h = np.square(np.clip(z, 0.0, 1.0))
    return h @ w1 + b1[0]


def rmse(a,b) -> float:
    return float(np.sqrt(np.mean(np.square(a.astype(np.float64)-b.astype(np.float64)))))


def mae(a,b) -> float:
    return float(np.mean(np.abs(a.astype(np.float64)-b.astype(np.float64))))


def trunc_div(v: np.ndarray, d: int) -> np.ndarray:
    q=v.astype(np.int64,copy=False)
    return np.where(q>=0,q//d,-((-q)//d))


class Adam:
    def __init__(self, arrays: list[np.ndarray], lr: float):
        self.lr=lr; self.m=[np.zeros_like(a,dtype=np.float32) for a in arrays]
        self.v=[np.zeros_like(a,dtype=np.float32) for a in arrays]; self.t=0
    def step(self, arrays, grads):
        self.t += 1; b1,b2=.9,.999; c1=1-b1**self.t; c2=1-b2**self.t
        for i,(a,g) in enumerate(zip(arrays,grads)):
            self.m[i]=b1*self.m[i]+(1-b1)*g; self.v[i]=b2*self.v[i]+(1-b2)*np.square(g)
            a -= self.lr*(self.m[i]/c1)/(np.sqrt(self.v[i]/c2)+1e-8)


def quantize(w0,b0,w1,b1):
    return (np.clip(np.rint(w0*QA),-32768,32767).astype(np.int16),
            np.clip(np.rint(b0*QA),-32768,32767).astype(np.int16),
            np.clip(np.rint(w1*QB),-32768,32767).astype(np.int16),
            np.clip(np.rint(b1*QA*QB),-(2**31),2**31-1).astype(np.int32))


def quant_forward_cp(data,qw0,qb0,qw1,qb1):
    ids,counts=data['ids'],data['counts']; acc=np.broadcast_to(qb0.astype(np.int32),(len(ids),len(qb0))).copy()
    for slot in range(ids.shape[1]):
        mask=counts>slot
        if np.any(mask): acc[mask]+=qw0[ids[mask,slot]].astype(np.int32)
    clip=np.clip(acc,0,QA).astype(np.int64)
    raw=(clip*clip)@qw1.astype(np.int64); scaled=trunc_div(raw,QA)+int(qb1[0])
    return trunc_div(scaled*CP_SCALE,QA*QB).astype(np.int32)


def split_metrics(data,mask,f,q):
    teacher,base,sign=data['teacher'][mask],data['baseline'][mask],data['side_sign'][mask]
    fs=base+sign*f[mask]*CP_SCALE; qs=base+sign*q[mask]
    return {'records':int(mask.sum()),'baseline_rmse_cp':rmse(teacher,base),
            'float_corrected_rmse_cp':rmse(teacher,fs),'quant_corrected_rmse_cp':rmse(teacher,qs),
            'baseline_mae_cp':mae(teacher,base),'float_corrected_mae_cp':mae(teacher,fs),
            'quant_corrected_mae_cp':mae(teacher,qs)}


def main() -> int:
    args=parse_args(); args.output_dir.mkdir(parents=True,exist_ok=False)
    data=build_dataset(args.teacher,args.engine_dir); codes=data['codes']; train_idx=np.flatnonzero(codes==0)
    if min(len(train_idx),int((codes==1).sum()),int((codes==2).sum()))==0: raise SystemExit('empty split')
    rng=np.random.default_rng(args.seed+args.hidden+9000)
    w0=rng.normal(0,.018,size=(FEATURES,args.hidden)).astype(np.float32); b0=np.full(args.hidden,.10,dtype=np.float32)
    w1=rng.normal(0,.02,size=args.hidden).astype(np.float32); b1=np.zeros(1,dtype=np.float32)
    arrays=[w0,b0,w1,b1]; opt=Adam(arrays,args.learning_rate); best_val=float('inf'); best=None; best_epoch=0; history=[]
    ids,counts,y=data['ids'],data['counts'],data['target']

    for epoch in range(1,args.epochs+1):
        order=rng.permutation(train_idx); loss=0.; examples=0
        for start in range(0,len(order),args.batch_size):
            idx=order[start:start+args.batch_size]; ib=ids[idx]; cb=counts[idx]; yb=y[idx]
            z=sparse_hidden(ib,cb,w0,b0); clipped=np.clip(z,0.,1.); h=np.square(clipped); pred=h@w1+b1[0]
            err=pred-yb; gp=np.clip(err,-.5,.5).astype(np.float32)/len(idx)
            loss += float(np.sum(np.where(np.abs(err)<=.5,.5*err*err,.5*(np.abs(err)-.25)))); examples+=len(idx)
            gw1=h.T@gp+args.weight_decay*w1; gb1=np.asarray([gp.sum()],dtype=np.float32)
            gh=gp[:,None]*w1[None,:]; gz=gh*(2*clipped)*((z>0)&(z<1)).astype(np.float32)
            gw0=args.weight_decay*w0
            # Scatter each active feature's row gradient. np.add.at handles repeated piece-square rows safely.
            for slot in range(MAX_ACTIVE):
                mask=cb>slot
                if np.any(mask): np.add.at(gw0,ib[mask,slot],gz[mask])
            opt.step(arrays,[gw0,gz.sum(axis=0),gw1,gb1])
        f=forward(data,w0,b0,w1,b1); vm=codes==1
        score=data['baseline'][vm]+data['side_sign'][vm]*f[vm]*CP_SCALE; val=rmse(data['teacher'][vm],score)
        row={'epoch':epoch,'mean_huber':loss/max(1,examples),'validation_float_rmse_cp':val}; history.append(row); print(json.dumps(row),flush=True)
        if val<best_val: best_val=val; best_epoch=epoch; best=[a.copy() for a in arrays]

    assert best is not None; w0[:],b0[:],w1[:],b1[:]=best
    f=forward(data,w0,b0,w1,b1); qw0,qb0,qw1,qb1=quantize(w0,b0,w1,b1); q=quant_forward_cp(data,qw0,qb0,qw1,qb1)
    metrics={n:split_metrics(data,codes==c,f,q) for n,c in (('train',0),('validation',1),('holdout',2))}
    meta={'schema_version':1,'architecture':f'king-context9-absolute768-h{args.hidden}-screlu-classical-replacement',
          'feature_count':FEATURES,'contexts':CONTEXTS,'hidden':args.hidden,'qa':QA,'qb':QB,'cp_scale':CP_SCALE,
          'target_clip_cp':TARGET_CLIP_CP,'best_epoch_by_validation_rmse':best_epoch,'best_validation_float_rmse_cp':best_val,
          'epochs_requested':args.epochs,'batch_size':args.batch_size,'learning_rate':args.learning_rate,'weight_decay':args.weight_decay,
          'seed':args.seed,'teacher_sha256':hashlib.sha256(args.teacher.read_bytes()).hexdigest(),'metrics':metrics,'history':history}
    np.savez_compressed(args.output_dir/f'context-h{args.hidden}.npz',feature_weights=qw0,feature_bias=qb0,output_weights=qw1,output_bias=qb1)
    (args.output_dir/'training-metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in meta.items() if k!='history'},indent=2,sort_keys=True))
    return 0

if __name__=='__main__': raise SystemExit(main())
