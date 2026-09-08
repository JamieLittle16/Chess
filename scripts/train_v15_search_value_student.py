#!/usr/bin/env python3
"""Train compact king-bucket residual students on Rust V15 search-backed values.

The teacher score is side-to-move centipawns from exact Rust V15 search. The deployed student stays
anchored to the Python evaluator: it predicts an antisymmetric White-perspective correction over the
V13 prefix, with the blend denominator selected on validation. This keeps runtime identical to the
previous bucket-student probe while changing only the supervision target.
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
FEATURES = 8 * 768
MAX_PIECES = 32


def args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--teacher", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--hidden", type=int, choices=(16, 32), required=True)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=256)
    p.add_argument("--lr", type=float, default=0.0015)
    p.add_argument("--weight-decay", type=float, default=2e-5)
    p.add_argument("--seed", type=int, default=20260908)
    return p.parse_args()


def feature_index(board: chess.Board, perspective: chess.Color, piece: chess.Piece, square: int) -> int:
    king = board.king(perspective)
    if king is None:
        raise ValueError("missing king")
    kf, kr = chess.square_file(king), chess.square_rank(king)
    if not perspective:
        kr = 7 - kr
    mirror = kf >= 4
    ckf = 7 - kf if mirror else kf
    bucket = (kr // 2) * 2 + (ckf // 2)
    ownership = 0 if piece.color == perspective else 1
    plane = ownership * 6 + piece.piece_type - 1
    f, r = chess.square_file(square), chess.square_rank(square)
    if not perspective:
        r = 7 - r
    if mirror:
        f = 7 - f
    return bucket * 768 + plane * 64 + r * 8 + f


def load_engine(engine_dir: Path):
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state, _evaluate_state_v13_only
    return encode_position, EVAL_WIDTH, _build_eval_state_into, _evaluate_state, _evaluate_state_v13_only


def build_dataset(path: Path, engine_dir: Path) -> dict[str, np.ndarray]:
    encode_position, width, build_state, eval_full, eval_v13 = load_engine(engine_dir)
    records = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        score = int(r["teacher_cp"])
        if abs(score) <= 5000:
            records.append(r)
    n = len(records)
    iw = np.zeros((n, MAX_PIECES), np.int32)
    ib = np.zeros_like(iw)
    mask = np.zeros((n, MAX_PIECES), np.float32)
    teacher = np.empty(n, np.float32)
    v13 = np.empty(n, np.float32)
    v14 = np.empty(n, np.float32)
    target = np.empty(n, np.float32)
    sign = np.empty(n, np.float32)
    codes = np.empty(n, np.int8)
    split_map = {"train": 0, "validation": 1, "holdout": 2}
    for i, r in enumerate(records):
        b = chess.Board(r["fen"])
        pieces = list(b.piece_map().items())
        mask[i, : len(pieces)] = 1.0
        for j, (sq, piece) in enumerate(pieces):
            iw[i, j] = feature_index(b, chess.WHITE, piece, sq)
            ib[i, j] = feature_index(b, chess.BLACK, piece, sq)
        e = encode_position(b)
        state = np.empty(width, np.int32)
        build_state(e.board, state)
        a = float(eval_v13(e.side, state))
        c = float(eval_full(e.side, state))
        t = float(r["teacher_cp"])
        s = 1.0 if b.turn else -1.0
        teacher[i], v13[i], v14[i], sign[i] = t, a, c, s
        target[i] = s * np.clip(t - a, -TARGET_CLIP_CP, TARGET_CLIP_CP) / CP_SCALE
        codes[i] = split_map[r["split"]]
    return {"iw": iw, "ib": ib, "mask": mask, "teacher": teacher, "v13": v13, "v14": v14, "target": target, "sign": sign, "codes": codes}


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(a.astype(np.float64) - b.astype(np.float64)))))


def mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float64) - b.astype(np.float64))))


def forward(d, W, bias, out, idx):
    m = d["mask"][idx, :, None]
    aw = bias + (W[d["iw"][idx]] * m).sum(1)
    ab = bias + (W[d["ib"][idx]] * m).sum(1)
    cw, cb = np.clip(aw, 0.0, 1.0), np.clip(ab, 0.0, 1.0)
    hw, hb = cw * cw, cb * cb
    return (hw - hb) @ out, (aw, ab, cw, cb, hw, hb)


def quantize(W, bias, out):
    qW = np.clip(np.rint(W * QA), -32768, 32767).astype(np.int16)
    qb = np.clip(np.rint(bias * QA), -32768, 32767).astype(np.int16)
    qo = np.clip(np.rint(out * QB), -32768, 32767).astype(np.int16)
    return qW, qb, qo


def tdiv(v, d):
    v = np.asarray(v, dtype=np.int64)
    return np.where(v >= 0, v // d, -((-v) // d))


def quant_pred_cp(d, qW, qb, qo, idx):
    m = d["mask"][idx, :, None].astype(np.int64)
    aw = qb.astype(np.int64) + (qW[d["iw"][idx]].astype(np.int64) * m).sum(1)
    ab = qb.astype(np.int64) + (qW[d["ib"][idx]].astype(np.int64) * m).sum(1)
    aw, ab = np.clip(aw, 0, QA), np.clip(ab, 0, QA)
    raw = ((aw * aw - ab * ab) * qo.astype(np.int64)).sum(1)
    return tdiv(tdiv(raw, QA) * CP_SCALE, QA * QB).astype(np.int32)


class Adam:
    def __init__(self, arrays, lr):
        self.lr = lr
        self.m = [np.zeros_like(a) for a in arrays]
        self.v = [np.zeros_like(a) for a in arrays]
        self.t = 0

    def step(self, arrays, grads):
        self.t += 1
        b1, b2 = 0.9, 0.999
        c1, c2 = 1 - b1**self.t, 1 - b2**self.t
        for i, (a, g) in enumerate(zip(arrays, grads)):
            self.m[i] = b1 * self.m[i] + (1 - b1) * g
            self.v[i] = b2 * self.v[i] + (1 - b2) * g * g
            a -= self.lr * (self.m[i] / c1) / (np.sqrt(self.v[i] / c2) + 1e-8)


def metrics(d, idx, corr, den):
    candidate = d["v13"][idx] + d["sign"][idx] * np.asarray(corr, np.float64) / den
    return {
        "records": int(len(idx)),
        "candidate_rmse_cp": rmse(d["teacher"][idx], candidate),
        "current_v14_rmse_cp": rmse(d["teacher"][idx], d["v14"][idx]),
        "v13_rmse_cp": rmse(d["teacher"][idx], d["v13"][idx]),
        "candidate_mae_cp": mae(d["teacher"][idx], candidate),
        "current_v14_mae_cp": mae(d["teacher"][idx], d["v14"][idx]),
    }


def main() -> int:
    a = args()
    a.output_dir.mkdir(parents=True, exist_ok=False)
    d = build_dataset(a.teacher, a.engine_dir)
    tr, va, ho = (np.flatnonzero(d["codes"] == k) for k in range(3))
    rng = np.random.default_rng(a.seed + a.hidden)
    W = rng.normal(0, 0.012, (FEATURES, a.hidden)).astype(np.float32)
    bias = np.full(a.hidden, 0.10, np.float32)
    out = rng.normal(0, 0.018, a.hidden).astype(np.float32)
    arrays = [W, bias, out]
    opt = Adam(arrays, a.lr)
    best = None
    best_rmse = float("inf")
    best_epoch = 0
    best_den = 1
    history = []
    denominators = (1, 2, 3, 4, 6, 8, 12)
    for epoch in range(1, a.epochs + 1):
        order = rng.permutation(tr)
        train_abs = 0.0
        for start in range(0, len(order), a.batch_size):
            ix = order[start : start + a.batch_size]
            pred, cache = forward(d, W, bias, out, ix)
            err = pred - d["target"][ix]
            gp = np.clip(err, -0.5, 0.5).astype(np.float32) / len(ix)
            train_abs += float(np.abs(err).sum())
            aw, ab, cw, cb, hw, hb = cache
            go = (hw - hb).T @ gp + a.weight_decay * out
            ghw = gp[:, None] * out[None, :]
            ghb = -ghw
            gaw = ghw * (2 * cw) * ((aw > 0) & (aw < 1))
            gab = ghb * (2 * cb) * ((ab > 0) & (ab < 1))
            gb = gaw.sum(0) + gab.sum(0)
            gW = a.weight_decay * W.copy()
            masks = d["mask"][ix]
            for row in range(len(ix)):
                active = masks[row] > 0
                np.add.at(gW, d["iw"][ix[row]][active], gaw[row])
                np.add.at(gW, d["ib"][ix[row]][active], gab[row])
            opt.step(arrays, [gW, gb, go])
        qW, qb, qo = quantize(W, bias, out)
        qcp = quant_pred_cp(d, qW, qb, qo, va)
        choices = []
        for den in denominators:
            candidate = d["v13"][va] + d["sign"][va] * qcp / den
            choices.append((rmse(d["teacher"][va], candidate), den))
        val_rmse, den = min(choices)
        row = {"epoch": epoch, "validation_quant_rmse_cp": val_rmse, "best_denominator": den, "mean_abs_train_target_error": train_abs / max(1, len(tr))}
        history.append(row)
        print(json.dumps(row), flush=True)
        if val_rmse < best_rmse:
            best_rmse, best_epoch, best_den = val_rmse, epoch, den
            best = (W.copy(), bias.copy(), out.copy())
    assert best is not None
    W, bias, out = best
    qW, qb, qo = quantize(W, bias, out)
    all_idx = np.arange(len(d["teacher"]))
    qall = quant_pred_cp(d, qW, qb, qo, all_idx)
    summary = {
        "architecture": f"search-value-kingbucket8-h{a.hidden}x2",
        "hidden_per_perspective": a.hidden,
        "live_accumulator_lanes": 2 * a.hidden,
        "model_int16_bytes": int(qW.nbytes + qb.nbytes + qo.nbytes),
        "best_epoch": best_epoch,
        "selected_scale_denominator": best_den,
        "teacher_sha256": hashlib.sha256(a.teacher.read_bytes()).hexdigest(),
        "records": int(len(all_idx)),
        "metrics": {
            "train": metrics(d, tr, qall[tr], best_den),
            "validation": metrics(d, va, qall[va], best_den),
            "holdout": metrics(d, ho, qall[ho], best_den),
        },
        "history": history,
    }
    np.savez_compressed(a.output_dir / f"search-value-h{a.hidden}.npz", feature_weights=qW, feature_bias=qb, output_weights=qo, scale_denominator=np.asarray([best_den], np.int32))
    (a.output_dir / "training-metadata.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps({k: v for k, v in summary.items() if k != "history"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
