#!/usr/bin/env python3
"""Train a tiny king-bucket student directly on the Rust-Gestalt error left by V14.

The earlier topology student learns Gestalt - V13 and therefore spends capacity reproducing
information already present in V14's accepted H64 student.  This trainer instead targets

    residual = exact Rust Gestalt teacher - current packaged V14 evaluation

on the real Rust search-leaf corpus.  The deployment can then keep V14 intact and add only this
missing king-conditioned information at qply==0.  H8/H12 are especially interesting because their
leaf rebuild cost is much smaller than the H16 full-Gestalt student.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import chess
import numpy as np

QA = 255
QB = 64
CP_SCALE = 400
TARGET_CLIP_CP = 1600
BUCKETS = 9
FEATURES = BUCKETS * 768
MAX_PIECES = 32
BUCKET_MAP = np.asarray([
    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,
    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,
    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,
], dtype=np.int16)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--teacher', type=Path, required=True)
    p.add_argument('--engine-dir', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    p.add_argument('--hidden', type=int, choices=(8, 12, 16), required=True)
    p.add_argument('--epochs', type=int, default=24)
    p.add_argument('--batch-size', type=int, default=256)
    p.add_argument('--lr', type=float, default=.0015)
    p.add_argument('--weight-decay', type=float, default=2e-5)
    p.add_argument('--seed', type=int, default=20260909)
    return p.parse_args()


def feature_index(board: chess.Board, perspective: bool, piece: chess.Piece, square: int) -> int:
    king = board.king(perspective)
    if king is None:
        raise ValueError('missing king')
    mapped = king if perspective else chess.square(chess.square_file(king), 7 - chess.square_rank(king))
    bucket = int(BUCKET_MAP[mapped]) % BUCKETS
    mirror = chess.square_file(king) >= 4
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    if mirror:
        file = 7 - file
    if not perspective:
        rank = 7 - rank
    ownership = 0 if piece.color == perspective else 1
    plane = ownership * 6 + (piece.piece_type - 1)
    return bucket * 768 + plane * 64 + rank * 8 + file


def load_engine(engine_dir: Path):
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state
    return encode_position, EVAL_WIDTH, _build_eval_state_into, _evaluate_state


def load_dataset(path: Path, engine_dir: Path) -> dict[str, np.ndarray]:
    encode_position, width, build_state, full_eval = load_engine(engine_dir)
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('teacher_mate') is None and abs(int(row['teacher_cp'])) <= 5000:
            rows.append(row)
    n = len(rows)
    iw = np.zeros((n, MAX_PIECES), np.int32)
    ib = np.zeros_like(iw)
    mask = np.zeros((n, MAX_PIECES), np.float32)
    teacher = np.empty(n, np.float32)
    v14 = np.empty(n, np.float32)
    target = np.empty(n, np.float32)
    stm_white = np.empty(n, np.bool_)
    codes = np.empty(n, np.int8)
    split_map = {'train': 0, 'validation': 1, 'holdout': 2}
    for i, row in enumerate(rows):
        board = chess.Board(row['fen'])
        pieces = list(board.piece_map().items())
        mask[i, :len(pieces)] = 1.0
        for j, (sq, piece) in enumerate(pieces):
            iw[i, j] = feature_index(board, chess.WHITE, piece, sq)
            ib[i, j] = feature_index(board, chess.BLACK, piece, sq)
        enc = encode_position(board)
        state = np.empty(width, np.int32)
        build_state(enc.board, state)
        base = float(full_eval(enc.side, state))
        teach = float(row['teacher_cp'])
        teacher[i] = teach
        v14[i] = base
        residual = max(-TARGET_CLIP_CP, min(TARGET_CLIP_CP, teach - base))
        target[i] = residual / CP_SCALE
        stm_white[i] = bool(board.turn)
        codes[i] = split_map[row['split']]
    return {
        'iw': iw, 'ib': ib, 'mask': mask, 'teacher': teacher, 'v14': v14,
        'target': target, 'stm_white': stm_white, 'codes': codes,
    }


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(a.astype(np.float64) - b.astype(np.float64)))))


def mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float64) - b.astype(np.float64))))


def forward(d, w, bias, out_us, out_them, ix):
    m = d['mask'][ix, :, None]
    aw = bias + (w[d['iw'][ix]] * m).sum(1)
    ab = bias + (w[d['ib'][ix]] * m).sum(1)
    cw = np.clip(aw, 0, 1)
    cb = np.clip(ab, 0, 1)
    hw = cw * cw
    hb = cb * cb
    sw = d['stm_white'][ix][:, None]
    us = np.where(sw, hw, hb)
    them = np.where(sw, hb, hw)
    return us @ out_us + them @ out_them, (aw, ab, cw, cb, sw, us, them)


def quantize(w, bias, out_us, out_them):
    qw = np.clip(np.rint(w * QA), -32768, 32767).astype(np.int16)
    qb = np.clip(np.rint(bias * QA), -32768, 32767).astype(np.int16)
    qu = np.clip(np.rint(out_us * QB), -32768, 32767).astype(np.int16)
    qt = np.clip(np.rint(out_them * QB), -32768, 32767).astype(np.int16)
    return qw, qb, qu, qt


def trunc_div(v, den):
    v = np.asarray(v, np.int64)
    return np.where(v >= 0, v // den, -((-v) // den))


def quantized_prediction(d, qw, qb, qu, qt, ix):
    m = d['mask'][ix, :, None].astype(np.int64)
    aw = qb.astype(np.int64) + (qw[d['iw'][ix]].astype(np.int64) * m).sum(1)
    ab = qb.astype(np.int64) + (qw[d['ib'][ix]].astype(np.int64) * m).sum(1)
    aw = np.clip(aw, 0, QA)
    ab = np.clip(ab, 0, QA)
    sw = d['stm_white'][ix][:, None]
    us = np.where(sw, aw, ab)
    them = np.where(sw, ab, aw)
    raw = ((us * us) * qu.astype(np.int64) + (them * them) * qt.astype(np.int64)).sum(1)
    return trunc_div(trunc_div(raw, QA) * CP_SCALE, QA * QB).astype(np.int32)


class Adam:
    def __init__(self, arrays, lr):
        self.lr = lr
        self.m = [np.zeros_like(x) for x in arrays]
        self.v = [np.zeros_like(x) for x in arrays]
        self.t = 0

    def step(self, arrays, grads):
        self.t += 1
        b1, b2 = .9, .999
        c1, c2 = 1 - b1 ** self.t, 1 - b2 ** self.t
        for i, (a, g) in enumerate(zip(arrays, grads)):
            self.m[i] = b1 * self.m[i] + (1 - b1) * g
            self.v[i] = b2 * self.v[i] + (1 - b2) * g * g
            a -= self.lr * (self.m[i] / c1) / (np.sqrt(self.v[i] / c2) + 1e-8)


def metrics(d, ix, residual_cp, den):
    candidate = d['v14'][ix] + residual_cp / den
    return {
        'records': int(len(ix)),
        'current_v14_rmse_cp': rmse(d['teacher'][ix], d['v14'][ix]),
        'candidate_rmse_cp': rmse(d['teacher'][ix], candidate),
        'current_v14_mae_cp': mae(d['teacher'][ix], d['v14'][ix]),
        'candidate_mae_cp': mae(d['teacher'][ix], candidate),
    }


def main() -> int:
    a = parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=False)
    d = load_dataset(a.teacher, a.engine_dir)
    train = np.flatnonzero(d['codes'] == 0)
    validation = np.flatnonzero(d['codes'] == 1)
    holdout = np.flatnonzero(d['codes'] == 2)
    rng = np.random.default_rng(a.seed + a.hidden)
    w = rng.normal(0, .012, (FEATURES, a.hidden)).astype(np.float32)
    bias = np.full(a.hidden, .1, np.float32)
    out_us = rng.normal(0, .018, a.hidden).astype(np.float32)
    out_them = rng.normal(0, .018, a.hidden).astype(np.float32)
    arrays = [w, bias, out_us, out_them]
    opt = Adam(arrays, a.lr)
    best = None
    best_key = (1e99, 0, 0)
    denominators = (1, 2, 3, 4, 6, 8, 12)

    for epoch in range(1, a.epochs + 1):
        order = rng.permutation(train)
        abs_loss = 0.0
        for start in range(0, len(order), a.batch_size):
            ix = order[start:start + a.batch_size]
            pred, cache = forward(d, w, bias, out_us, out_them, ix)
            err = pred - d['target'][ix]
            grad_pred = np.clip(err, -.5, .5).astype(np.float32) / len(ix)
            abs_loss += float(np.abs(err).sum())
            aw, ab, cw, cb, sw, us, them = cache
            grad_out_us = us.T @ grad_pred + a.weight_decay * out_us
            grad_out_them = them.T @ grad_pred + a.weight_decay * out_them
            grad_us = grad_pred[:, None] * out_us[None, :]
            grad_them = grad_pred[:, None] * out_them[None, :]
            grad_hw = np.where(sw, grad_us, grad_them)
            grad_hb = np.where(sw, grad_them, grad_us)
            grad_aw = grad_hw * (2 * cw) * ((aw > 0) & (aw < 1))
            grad_ab = grad_hb * (2 * cb) * ((ab > 0) & (ab < 1))
            grad_bias = grad_aw.sum(0) + grad_ab.sum(0)
            grad_w = a.weight_decay * w.copy()
            masks = d['mask'][ix]
            for row in range(len(ix)):
                active = masks[row] > 0
                np.add.at(grad_w, d['iw'][ix[row]][active], grad_aw[row])
                np.add.at(grad_w, d['ib'][ix[row]][active], grad_ab[row])
            opt.step(arrays, [grad_w, grad_bias, grad_out_us, grad_out_them])

        qw, qb, qu, qt = quantize(w, bias, out_us, out_them)
        qres = quantized_prediction(d, qw, qb, qu, qt, validation)
        choices = []
        for den in denominators:
            candidate = d['v14'][validation] + qres / den
            choices.append((rmse(d['teacher'][validation], candidate), den))
        val_rmse, den = min(choices)
        print(json.dumps({
            'epoch': epoch,
            'validation_rmse_cp': val_rmse,
            'den': den,
            'train_abs_scaled': abs_loss / max(1, len(train)),
        }), flush=True)
        if val_rmse < best_key[0]:
            best_key = (val_rmse, den, epoch)
            best = tuple(x.copy() for x in arrays)

    assert best is not None
    w, bias, out_us, out_them = best
    qw, qb, qu, qt = quantize(w, bias, out_us, out_them)
    den = best_key[1]
    all_ix = np.arange(len(d['teacher']))
    qres = quantized_prediction(d, qw, qb, qu, qt, all_ix)
    meta = {
        'architecture': f'gestalt-minus-v14-kingbucket-h{a.hidden}x2',
        'hidden': a.hidden,
        'live_lanes': 2 * a.hidden,
        'feature_rows': FEATURES,
        'model_int16_bytes': int(qw.nbytes + qb.nbytes + qu.nbytes + qt.nbytes),
        'best_epoch': best_key[2],
        'scale_denominator': den,
        'records': int(len(all_ix)),
        'metrics': {
            'train': metrics(d, train, qres[train], den),
            'validation': metrics(d, validation, qres[validation], den),
            'holdout': metrics(d, holdout, qres[holdout], den),
        },
        'teacher_sha256': hashlib.sha256(a.teacher.read_bytes()).hexdigest(),
    }
    np.savez_compressed(
        a.output_dir / f'gestalt-direct-residual-h{a.hidden}.npz',
        feature_weights=qw,
        feature_bias=qb,
        output_us=qu,
        output_them=qt,
        scale_denominator=np.asarray([den], np.int32),
    )
    (a.output_dir / 'metadata.json').write_text(json.dumps(meta, indent=2) + '\n')
    print('FINAL', json.dumps(meta), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
