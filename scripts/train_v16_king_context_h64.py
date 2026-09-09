#!/usr/bin/env python3
"""Fine-tune the proven V15 H64 student with sparse king-zone context toward Gestalt.

The deployed architecture remains one 64-lane accumulator.  The first 768 feature rows are
piece-square rows identical to V15.  Sixteen new rows encode the white and black king zones
(8 buckets each).  At runtime those two rows are added immediately before SCReLU, so ordinary
piece moves do not widen or update the accumulator.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import chess
import numpy as np

PIECE_FEATURES = 768
KING_BUCKETS = 8
INPUTS = PIECE_FEATURES + 2 * KING_BUCKETS
HIDDEN = 64
QA = 255
QB = 64
CP_SCALE = 400
DEPLOY_DEN = 12
TARGET_CLIP_CP = 1200


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--teacher", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--alpha", type=float, required=True)
    p.add_argument("--epochs", type=int, default=50)
    p.add_argument("--batch-size", type=int, default=384)
    p.add_argument("--learning-rate", type=float, default=0.0010)
    p.add_argument("--weight-decay", type=float, default=1e-5)
    p.add_argument("--anchor-lambda", type=float, default=0.00035)
    p.add_argument("--seed", type=int, default=20260909)
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


def float_from_quant(q: np.ndarray, scale: int) -> np.ndarray:
    return q.astype(np.float32) / float(scale)


def quantize(w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> tuple[np.ndarray, ...]:
    return (
        np.clip(np.rint(w0 * QA), -32768, 32767).astype(np.int16),
        np.clip(np.rint(b0 * QA), -32768, 32767).astype(np.int16),
        np.clip(np.rint(w1 * QB), -32768, 32767).astype(np.int16),
        np.clip(np.rint(b1 * QA * QB), -(2**31), 2**31 - 1).astype(np.int32),
    )


def quant_forward_raw_cp(x: np.ndarray, qw0: np.ndarray, qb0: np.ndarray, qw1: np.ndarray, qb1: np.ndarray) -> np.ndarray:
    accum = x.astype(np.int32) @ qw0.astype(np.int32) + qb0.astype(np.int32)
    clipped = np.clip(accum, 0, QA).astype(np.int64)
    raw = (clipped * clipped) @ qw1.astype(np.int64)
    scaled = trunc_div(raw, QA) + int(qb1[0])
    return trunc_div(scaled * CP_SCALE, QA * QB).astype(np.int32)


def float_forward(x: np.ndarray, w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> np.ndarray:
    z = x @ w0 + b0
    h = np.square(np.clip(z, 0.0, 1.0))
    return h @ w1 + b1[0]


class Adam:
    def __init__(self, arrays: list[np.ndarray], lr: float) -> None:
        self.lr = lr
        self.m = [np.zeros_like(a, dtype=np.float32) for a in arrays]
        self.v = [np.zeros_like(a, dtype=np.float32) for a in arrays]
        self.t = 0

    def step(self, arrays: list[np.ndarray], grads: list[np.ndarray]) -> None:
        self.t += 1
        beta1, beta2 = 0.9, 0.999
        c1, c2 = 1.0 - beta1**self.t, 1.0 - beta2**self.t
        for i, (array, grad) in enumerate(zip(arrays, grads)):
            self.m[i] = beta1 * self.m[i] + (1.0 - beta1) * grad
            self.v[i] = beta2 * self.v[i] + (1.0 - beta2) * np.square(grad)
            array -= self.lr * (self.m[i] / c1) / (np.sqrt(self.v[i] / c2) + 1e-8)


def load_engine(engine: Path):
    sys.path.insert(0, str(engine.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state_v13_only
    return encode_position, _build_eval_state_into, _evaluate_state_v13_only, int(EVAL_WIDTH)


def main() -> int:
    a = parse_args()
    if not (0.0 < a.alpha <= 1.0):
        raise SystemExit("alpha must be in (0, 1]")
    a.output_dir.mkdir(parents=True, exist_ok=True)

    model_path = a.engine_dir / "experiments" / "v14_student_h64.npz"
    with np.load(model_path) as z:
        q_old_w0 = z["feature_weights"].astype(np.int16)
        q_old_b0 = z["feature_bias"].astype(np.int16)
        q_old_w1 = z["output_weights"].astype(np.int16)
        q_old_b1 = z["output_bias"].astype(np.int32)
    if q_old_w0.shape != (PIECE_FEATURES, HIDDEN):
        raise SystemExit(f"unexpected baseline model shape {q_old_w0.shape}")

    rows = []
    for line in a.teacher.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("teacher_mate") is None and abs(int(row["teacher_cp"])) <= 5000:
            rows.append(row)
    if not rows:
        raise SystemExit("no usable teacher rows")

    encode_position, build_state, v13_eval, eval_width = load_engine(a.engine_dir)
    n = len(rows)
    x = np.zeros((n, INPUTS), dtype=np.float32)
    teacher = np.empty(n, dtype=np.float32)
    v13 = np.empty(n, dtype=np.float32)
    sign = np.empty(n, dtype=np.float32)
    split = np.empty(n, dtype=np.int8)
    split_map = {"train": 0, "validation": 1, "holdout": 2}

    old_x = np.zeros((n, PIECE_FEATURES), dtype=np.float32)
    for i, row in enumerate(rows):
        board = chess.Board(row["fen"])
        for square, piece in board.piece_map().items():
            idx = feature_index(piece, square)
            x[i, idx] = 1.0
            old_x[i, idx] = 1.0
        white_king = board.king(chess.WHITE)
        black_king = board.king(chess.BLACK)
        if white_king is None or black_king is None:
            raise SystemExit("teacher row missing king")
        x[i, PIECE_FEATURES + king_bucket(white_king, True)] = 1.0
        x[i, PIECE_FEATURES + KING_BUCKETS + king_bucket(black_king, False)] = 1.0
        enc = encode_position(board)
        state = np.empty(eval_width, dtype=np.int32)
        build_state(enc.board, state)
        v13[i] = int(v13_eval(enc.side, state))
        teacher[i] = int(row["teacher_cp"])
        sign[i] = 1.0 if board.turn == chess.WHITE else -1.0
        split[i] = split_map[str(row["split"])]

    old_raw_white = quant_forward_raw_cp(old_x, q_old_w0, q_old_b0, q_old_w1, q_old_b1).astype(np.float32)
    old_deployed_stm = v13 + sign * trunc_div(old_raw_white.astype(np.int64), DEPLOY_DEN).astype(np.float32)
    delta = np.clip(teacher - old_deployed_stm, -TARGET_CLIP_CP, TARGET_CLIP_CP)
    desired_stm = old_deployed_stm + a.alpha * delta
    # Student raw output is white-perspective and is divided by DEPLOY_DEN in production.
    y = sign * (desired_stm - v13) * DEPLOY_DEN / CP_SCALE

    w0 = np.zeros((INPUTS, HIDDEN), dtype=np.float32)
    w0[:PIECE_FEATURES] = float_from_quant(q_old_w0, QA)
    b0 = float_from_quant(q_old_b0, QA)
    w1 = float_from_quant(q_old_w1, QB)
    b1 = q_old_b1.astype(np.float32) / float(QA * QB)
    anchor_w0 = w0.copy()
    anchor_b0 = b0.copy()
    anchor_w1 = w1.copy()
    anchor_b1 = b1.copy()
    arrays = [w0, b0, w1, b1]
    opt = Adam(arrays, a.learning_rate)
    rng = np.random.default_rng(a.seed + int(round(a.alpha * 1000)))

    train_idx = np.flatnonzero(split == 0)
    val_idx = np.flatnonzero(split == 1)
    hold_idx = np.flatnonzero(split == 2)
    best = None
    best_rmse = float("inf")
    history = []

    for epoch in range(1, a.epochs + 1):
        order = rng.permutation(train_idx)
        for start in range(0, len(order), a.batch_size):
            ii = order[start : start + a.batch_size]
            xb, yb = x[ii], y[ii]
            z = xb @ w0 + b0
            c = np.clip(z, 0.0, 1.0)
            h = c * c
            pred = h @ w1 + b1[0]
            err = pred - yb
            gp = np.clip(err, -0.5, 0.5).astype(np.float32) / len(ii)
            gw1 = h.T @ gp + a.weight_decay * w1 + a.anchor_lambda * (w1 - anchor_w1)
            gb1 = np.asarray([gp.sum()], np.float32) + a.anchor_lambda * (b1 - anchor_b1)
            gh = gp[:, None] * w1[None, :]
            gz = gh * (2.0 * c) * ((z > 0.0) & (z < 1.0))
            gw0 = xb.T @ gz + a.weight_decay * w0 + a.anchor_lambda * (w0 - anchor_w0)
            gb0 = gz.sum(0) + a.anchor_lambda * (b0 - anchor_b0)
            opt.step(arrays, [gw0, gb0, gw1, gb1])

        pred = float_forward(x[val_idx], w0, b0, w1, b1)
        rmse = float(np.sqrt(np.mean(np.square(pred - y[val_idx], dtype=np.float64))))
        history.append({"epoch": epoch, "validation_target_rmse_norm": rmse})
        print(json.dumps(history[-1]), flush=True)
        if rmse < best_rmse:
            best_rmse = rmse
            best = [value.copy() for value in arrays]

    if best is None:
        raise AssertionError("no checkpoint")
    w0[:], b0[:], w1[:], b1[:] = best
    qw0, qb0, qw1, qb1 = quantize(w0, b0, w1, b1)
    raw_cp = quant_forward_raw_cp(x, qw0, qb0, qw1, qb1).astype(np.float32)
    deployed_stm = v13 + sign * trunc_div(raw_cp.astype(np.int64), DEPLOY_DEN).astype(np.float32)

    def metrics(indices: np.ndarray) -> dict[str, float | int]:
        return {
            "records": int(len(indices)),
            "teacher_rmse_old_cp": float(np.sqrt(np.mean(np.square(teacher[indices] - old_deployed_stm[indices], dtype=np.float64)))),
            "teacher_rmse_new_cp": float(np.sqrt(np.mean(np.square(teacher[indices] - deployed_stm[indices], dtype=np.float64)))),
            "mean_abs_delta_from_old_cp": float(np.mean(np.abs(deployed_stm[indices] - old_deployed_stm[indices]))),
        }

    metadata = {
        "schema": 1,
        "architecture": "piece768+whiteKingZone8+blackKingZone8-h64-screlu-residual-on-v13",
        "alpha": a.alpha,
        "deploy_denominator": DEPLOY_DEN,
        "best_validation_target_rmse_norm": best_rmse,
        "teacher_sha256": hashlib.sha256(a.teacher.read_bytes()).hexdigest(),
        "baseline_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "metrics": {"train": metrics(train_idx), "validation": metrics(val_idx), "holdout": metrics(hold_idx)},
        "history": history,
    }
    np.savez_compressed(
        a.output_dir / "student-h64-king-context.npz",
        feature_weights=qw0,
        feature_bias=qb0,
        output_weights=qw1,
        output_bias=qb1,
    )
    (a.output_dir / "training-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps({key: value for key, value in metadata.items() if key != "history"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
