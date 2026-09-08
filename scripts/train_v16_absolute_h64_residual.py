#!/usr/bin/env python3
"""Train an exact V14-shape absolute768 H64 residual against blended teacher labels."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import chess
import numpy as np

INPUTS = 768
HIDDEN = 64
QA = 255
QB = 64
CP_SCALE = 400
TARGET_CLIP_CP = 1600


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--teacher", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--epochs", type=int, default=30)
    p.add_argument("--batch-size", type=int, default=512)
    p.add_argument("--learning-rate", type=float, default=0.002)
    p.add_argument("--weight-decay", type=float, default=0.00002)
    p.add_argument("--seed", type=int, default=20260908)
    return p.parse_args()


def feature_index(piece: chess.Piece, square: int) -> int:
    return (0 if piece.color == chess.WHITE else 384) + (piece.piece_type - 1) * 64 + square


def load_api(engine_dir: Path) -> tuple[Any, Any, Any, int]:
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state_v13_only
    return encode_position, _build_eval_state_into, _evaluate_state_v13_only, int(EVAL_WIDTH)


def build_dataset(path: Path, engine_dir: Path) -> dict[str, np.ndarray]:
    encode_position, build_state, evaluate_v13, eval_width = load_api(engine_dir)
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("teacher_mate") is not None or abs(int(record["teacher_cp"])) > 5000:
            continue
        rows.append(record)
    if not rows:
        raise ValueError("teacher corpus had no usable non-mate rows")

    x = np.zeros((len(rows), INPUTS), dtype=np.float32)
    teacher = np.empty(len(rows), dtype=np.float32)
    baseline = np.empty(len(rows), dtype=np.float32)
    target_abs = np.empty(len(rows), dtype=np.float32)
    side_sign = np.empty(len(rows), dtype=np.float32)
    split_code = np.empty(len(rows), dtype=np.int8)
    split_map = {"train": 0, "validation": 1, "holdout": 2}

    for i, record in enumerate(rows):
        board = chess.Board(record["fen"])
        for square, piece in board.piece_map().items():
            x[i, feature_index(piece, square)] = 1.0
        encoded = encode_position(board)
        state = np.empty(eval_width, dtype=np.int32)
        build_state(encoded.board, state)
        base_cp = int(evaluate_v13(encoded.side, state))
        teacher_cp = int(record["teacher_cp"])
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        residual_stm = max(-TARGET_CLIP_CP, min(TARGET_CLIP_CP, teacher_cp - base_cp))
        teacher[i] = teacher_cp
        baseline[i] = base_cp
        side_sign[i] = sign
        target_abs[i] = sign * residual_stm / CP_SCALE
        split = str(record["split"])
        if split not in split_map:
            raise ValueError(f"unknown split {split!r}")
        split_code[i] = split_map[split]
    return {
        "x": x,
        "teacher": teacher,
        "baseline": baseline,
        "target_abs": target_abs,
        "side_sign": side_sign,
        "split_code": split_code,
    }


def rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(a.astype(np.float64) - b.astype(np.float64)))))


def mae(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float64) - b.astype(np.float64))))


def trunc_div(values: np.ndarray, divisor: int) -> np.ndarray:
    values = values.astype(np.int64, copy=False)
    return np.where(values >= 0, values // divisor, -((-values) // divisor))


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
        for i, (array, grad) in enumerate(zip(arrays, grads)):
            self.m[i] = b1 * self.m[i] + (1.0 - b1) * grad
            self.v[i] = b2 * self.v[i] + (1.0 - b2) * np.square(grad)
            array -= self.lr * (self.m[i] / c1) / (np.sqrt(self.v[i] / c2) + 1e-8)


def float_forward(x: np.ndarray, w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> np.ndarray:
    z = x @ w0 + b0
    h = np.square(np.clip(z, 0.0, 1.0))
    return h @ w1 + b1[0]


def quantize(w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> tuple[np.ndarray, ...]:
    return (
        np.clip(np.rint(w0 * QA), -32768, 32767).astype(np.int16),
        np.clip(np.rint(b0 * QA), -32768, 32767).astype(np.int16),
        np.clip(np.rint(w1 * QB), -32768, 32767).astype(np.int16),
        np.clip(np.rint(b1 * QA * QB), -(2**31), 2**31 - 1).astype(np.int32),
    )


def quant_forward_cp(x: np.ndarray, q_w0: np.ndarray, q_b0: np.ndarray, q_w1: np.ndarray, q_b1: np.ndarray) -> np.ndarray:
    accum = x.astype(np.int32) @ q_w0.astype(np.int32) + q_b0.astype(np.int32)
    clipped = np.clip(accum, 0, QA).astype(np.int64)
    raw = (clipped * clipped) @ q_w1.astype(np.int64)
    scaled = trunc_div(raw, QA) + int(q_b1[0])
    return trunc_div(scaled * CP_SCALE, QA * QB).astype(np.int32)


def split_metrics(data: dict[str, np.ndarray], mask: np.ndarray, f: np.ndarray, q: np.ndarray) -> dict[str, float | int]:
    teacher = data["teacher"][mask]
    baseline = data["baseline"][mask]
    sign = data["side_sign"][mask]
    float_score = baseline + sign * f[mask] * CP_SCALE
    quant_score = baseline + sign * q[mask]
    return {
        "records": int(mask.sum()),
        "baseline_rmse_cp": rmse(teacher, baseline),
        "float_corrected_rmse_cp": rmse(teacher, float_score),
        "quant_corrected_rmse_cp": rmse(teacher, quant_score),
        "baseline_mae_cp": mae(teacher, baseline),
        "float_corrected_mae_cp": mae(teacher, float_score),
        "quant_corrected_mae_cp": mae(teacher, quant_score),
    }


def main() -> int:
    args = parse_args()
    if args.epochs <= 0 or args.batch_size <= 0 or args.learning_rate <= 0:
        raise SystemExit("epochs, batch-size and learning-rate must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    data = build_dataset(args.teacher, args.engine_dir)
    x, y, codes = data["x"], data["target_abs"], data["split_code"]
    train_idx = np.flatnonzero(codes == 0)
    if min(len(train_idx), int((codes == 1).sum()), int((codes == 2).sum())) == 0:
        raise SystemExit("train/validation/holdout must all be non-empty")

    rng = np.random.default_rng(args.seed + HIDDEN)
    w0 = rng.normal(0.0, 0.018, size=(INPUTS, HIDDEN)).astype(np.float32)
    b0 = np.full(HIDDEN, 0.10, dtype=np.float32)
    w1 = rng.normal(0.0, 0.02, size=HIDDEN).astype(np.float32)
    b1 = np.zeros(1, dtype=np.float32)
    arrays = [w0, b0, w1, b1]
    opt = Adam(arrays, args.learning_rate)
    best_val = float("inf")
    best_epoch = 0
    best: list[np.ndarray] | None = None
    history: list[dict[str, float | int]] = []

    for epoch in range(1, args.epochs + 1):
        order = rng.permutation(train_idx)
        total_loss = 0.0
        examples = 0
        for start in range(0, len(order), args.batch_size):
            idx = order[start:start + args.batch_size]
            xb, yb = x[idx], y[idx]
            z = xb @ w0 + b0
            clipped = np.clip(z, 0.0, 1.0)
            hidden = np.square(clipped)
            pred = hidden @ w1 + b1[0]
            error = pred - yb
            grad_pred = np.clip(error, -0.5, 0.5).astype(np.float32) / len(idx)
            total_loss += float(np.sum(np.where(np.abs(error) <= 0.5, 0.5 * error * error, 0.5 * (np.abs(error) - 0.25))))
            examples += len(idx)
            grad_w1 = hidden.T @ grad_pred + args.weight_decay * w1
            grad_b1 = np.asarray([grad_pred.sum()], dtype=np.float32)
            grad_hidden = grad_pred[:, None] * w1[None, :]
            grad_z = grad_hidden * (2.0 * clipped) * ((z > 0.0) & (z < 1.0)).astype(np.float32)
            opt.step(arrays, [xb.T @ grad_z + args.weight_decay * w0, grad_z.sum(axis=0), grad_w1, grad_b1])

        forward = float_forward(x, w0, b0, w1, b1)
        validation = codes == 1
        score = data["baseline"][validation] + data["side_sign"][validation] * forward[validation] * CP_SCALE
        val = rmse(data["teacher"][validation], score)
        row = {"epoch": epoch, "mean_huber": total_loss / max(1, examples), "validation_float_rmse_cp": val}
        history.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
        if val < best_val:
            best_val, best_epoch, best = val, epoch, [array.copy() for array in arrays]

    assert best is not None
    w0[:], b0[:], w1[:], b1[:] = best
    forward = float_forward(x, w0, b0, w1, b1)
    q_w0, q_b0, q_w1, q_b1 = quantize(w0, b0, w1, b1)
    quant = quant_forward_cp(x, q_w0, q_b0, q_w1, q_b1)
    metrics = {
        name: split_metrics(data, codes == code, forward, quant)
        for name, code in (("train", 0), ("validation", 1), ("holdout", 2))
    }
    metadata = {
        "schema_version": 1,
        "architecture": "absolute768-single-64-screlu-v13-baseline",
        "feature_count": INPUTS,
        "hidden": HIDDEN,
        "qa": QA,
        "qb": QB,
        "cp_scale": CP_SCALE,
        "target_clip_cp": TARGET_CLIP_CP,
        "best_epoch_by_validation_rmse": best_epoch,
        "best_validation_float_rmse_cp": best_val,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "seed": args.seed,
        "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
        "metrics": metrics,
        "history": history,
    }
    np.savez_compressed(
        args.output_dir / "v14_student_h64.npz",
        feature_weights=q_w0,
        feature_bias=q_b0,
        output_weights=q_w1,
        output_bias=q_b1,
    )
    (args.output_dir / "training-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps({k: v for k, v in metadata.items() if k != "history"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
