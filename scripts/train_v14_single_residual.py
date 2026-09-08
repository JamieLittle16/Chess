#!/usr/bin/env python3
"""Train the V14 absolute768 single-accumulator residual student on top of exact V13 evaluation.

The network predicts a White-perspective correction to *current V13*, not a replacement score. Zero
output is therefore exactly the V13 baseline. Model selection uses validation RMSE only; holdout is
reported once after restoring the best validation epoch. Both float and exact integer-quantised
inference are measured before any model is allowed into search.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import chess
import numpy as np

INPUTS = 768
QA = 255
QB = 64
CP_SCALE = 400
TARGET_CLIP_CP = 1200
ALLOWED_HIDDEN = (64, 96)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--engine-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--hidden", type=int, choices=ALLOWED_HIDDEN, required=True)
    parser.add_argument("--epochs", type=int, default=60)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=0.003)
    parser.add_argument("--weight-decay", type=float, default=0.00001)
    parser.add_argument("--seed", type=int, default=20260908)
    return parser.parse_args()


def feature_index(piece: chess.Piece, square: int) -> int:
    color_base = 0 if piece.color == chess.WHITE else 384
    return color_base + (piece.piece_type - 1) * 64 + square


def load_v13_api(engine_dir: Path) -> tuple[Any, Any, Any, int]:
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state
    return encode_position, _build_eval_state_into, _evaluate_state, int(EVAL_WIDTH)


def build_dataset(path: Path, engine_dir: Path) -> dict[str, np.ndarray]:
    encode_position, build_state, evaluate_state, eval_width = load_v13_api(engine_dir)
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("teacher_mate") is not None:
                continue
            teacher_cp = int(record["teacher_cp"])
            if abs(teacher_cp) > 5000:
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

    for index, record in enumerate(rows):
        board = chess.Board(record["fen"])
        for square, piece in board.piece_map().items():
            x[index, feature_index(piece, square)] = 1.0
        encoded = encode_position(board)
        state = np.empty(eval_width, dtype=np.int32)
        build_state(encoded.board, state)
        v13_cp = int(evaluate_state(encoded.side, state))
        sf_cp = int(record["teacher_cp"])
        sign = 1.0 if board.turn == chess.WHITE else -1.0
        residual_stm = max(-TARGET_CLIP_CP, min(TARGET_CLIP_CP, sf_cp - v13_cp))
        teacher[index] = sf_cp
        baseline[index] = v13_cp
        side_sign[index] = sign
        target_abs[index] = sign * residual_stm / CP_SCALE
        split = str(record["split"])
        if split not in split_map:
            raise ValueError(f"unknown split {split!r}")
        split_code[index] = split_map[split]

    return {
        "x": x,
        "teacher": teacher,
        "baseline": baseline,
        "target_abs": target_abs,
        "side_sign": side_sign,
        "split_code": split_code,
    }


def rmse(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(actual.astype(np.float64) - predicted.astype(np.float64)))))


def mae(actual: np.ndarray, predicted: np.ndarray) -> float:
    return float(np.mean(np.abs(actual.astype(np.float64) - predicted.astype(np.float64))))


def trunc_div(values: np.ndarray, divisor: int) -> np.ndarray:
    values = values.astype(np.int64, copy=False)
    return np.where(values >= 0, values // divisor, -((-values) // divisor))


class Adam:
    def __init__(self, arrays: list[np.ndarray], lr: float) -> None:
        self.lr = lr
        self.m = [np.zeros_like(array, dtype=np.float32) for array in arrays]
        self.v = [np.zeros_like(array, dtype=np.float32) for array in arrays]
        self.t = 0

    def step(self, arrays: list[np.ndarray], grads: list[np.ndarray]) -> None:
        self.t += 1
        b1 = 0.9
        b2 = 0.999
        correction1 = 1.0 - b1**self.t
        correction2 = 1.0 - b2**self.t
        for index, (array, grad) in enumerate(zip(arrays, grads)):
            self.m[index] = b1 * self.m[index] + (1.0 - b1) * grad
            self.v[index] = b2 * self.v[index] + (1.0 - b2) * np.square(grad)
            m_hat = self.m[index] / correction1
            v_hat = self.v[index] / correction2
            array -= self.lr * m_hat / (np.sqrt(v_hat) + 1e-8)


def float_forward(x: np.ndarray, w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> np.ndarray:
    z = x @ w0 + b0
    clipped = np.clip(z, 0.0, 1.0)
    hidden = np.square(clipped)
    return hidden @ w1 + b1[0]


def quantize(w0: np.ndarray, b0: np.ndarray, w1: np.ndarray, b1: np.ndarray) -> tuple[np.ndarray, ...]:
    q_w0 = np.clip(np.rint(w0 * QA), -32768, 32767).astype(np.int16)
    q_b0 = np.clip(np.rint(b0 * QA), -32768, 32767).astype(np.int16)
    q_w1 = np.clip(np.rint(w1 * QB), -32768, 32767).astype(np.int16)
    q_b1 = np.clip(np.rint(b1 * QA * QB), -(2**31), 2**31 - 1).astype(np.int32)
    return q_w0, q_b0, q_w1, q_b1


def quant_forward_cp(x: np.ndarray, q_w0: np.ndarray, q_b0: np.ndarray, q_w1: np.ndarray, q_b1: np.ndarray) -> np.ndarray:
    accum = x.astype(np.int32) @ q_w0.astype(np.int32) + q_b0.astype(np.int32)
    clipped = np.clip(accum, 0, QA).astype(np.int64)
    screlu = clipped * clipped
    raw = screlu @ q_w1.astype(np.int64)
    scaled = trunc_div(raw, QA) + int(q_b1[0])
    return trunc_div(scaled * CP_SCALE, QA * QB).astype(np.int32)


def split_metrics(
    dataset: dict[str, np.ndarray],
    mask: np.ndarray,
    float_abs_norm: np.ndarray,
    quant_abs_cp: np.ndarray,
) -> dict[str, float | int]:
    teacher = dataset["teacher"][mask]
    baseline = dataset["baseline"][mask]
    sign = dataset["side_sign"][mask]
    float_score = baseline + sign * float_abs_norm[mask] * CP_SCALE
    quant_score = baseline + sign * quant_abs_cp[mask]
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
    x = data["x"]
    y = data["target_abs"]
    codes = data["split_code"]
    train_idx = np.flatnonzero(codes == 0)
    validation_idx = np.flatnonzero(codes == 1)
    holdout_idx = np.flatnonzero(codes == 2)
    if min(len(train_idx), len(validation_idx), len(holdout_idx)) == 0:
        raise SystemExit("train/validation/holdout must all be non-empty")

    rng = np.random.default_rng(args.seed + args.hidden)
    w0 = rng.normal(0.0, 0.018, size=(INPUTS, args.hidden)).astype(np.float32)
    b0 = np.full(args.hidden, 0.10, dtype=np.float32)
    w1 = rng.normal(0.0, 0.02, size=args.hidden).astype(np.float32)
    b1 = np.zeros(1, dtype=np.float32)
    arrays = [w0, b0, w1, b1]
    optimiser = Adam(arrays, args.learning_rate)

    best_val_rmse = float("inf")
    best_epoch = 0
    best_arrays: list[np.ndarray] | None = None
    history: list[dict[str, float | int]] = []

    for epoch in range(1, args.epochs + 1):
        order = rng.permutation(train_idx)
        epoch_loss = 0.0
        examples = 0
        for start in range(0, len(order), args.batch_size):
            indices = order[start : start + args.batch_size]
            xb = x[indices]
            yb = y[indices]
            z = xb @ w0 + b0
            clipped = np.clip(z, 0.0, 1.0)
            hidden = np.square(clipped)
            pred = hidden @ w1 + b1[0]
            error = pred - yb
            # Huber derivative in normalised units: 0.5 == 200cp.
            grad_pred = np.clip(error, -0.5, 0.5).astype(np.float32) / len(indices)
            epoch_loss += float(np.sum(np.where(np.abs(error) <= 0.5, 0.5 * error * error, 0.5 * (np.abs(error) - 0.25))))
            examples += len(indices)

            grad_w1 = hidden.T @ grad_pred + args.weight_decay * w1
            grad_b1 = np.asarray([grad_pred.sum()], dtype=np.float32)
            grad_hidden = grad_pred[:, None] * w1[None, :]
            active = ((z > 0.0) & (z < 1.0)).astype(np.float32)
            grad_z = grad_hidden * (2.0 * clipped) * active
            grad_w0 = xb.T @ grad_z + args.weight_decay * w0
            grad_b0 = grad_z.sum(axis=0)
            optimiser.step(arrays, [grad_w0, grad_b0, grad_w1, grad_b1])

        float_abs = float_forward(x, w0, b0, w1, b1)
        val_mask = codes == 1
        val_teacher = data["teacher"][val_mask]
        val_score = data["baseline"][val_mask] + data["side_sign"][val_mask] * float_abs[val_mask] * CP_SCALE
        val_rmse = rmse(val_teacher, val_score)
        row = {"epoch": epoch, "mean_huber": epoch_loss / max(1, examples), "validation_float_rmse_cp": val_rmse}
        history.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
        if val_rmse < best_val_rmse:
            best_val_rmse = val_rmse
            best_epoch = epoch
            best_arrays = [array.copy() for array in arrays]

    if best_arrays is None:
        raise AssertionError("no best model selected")
    w0[:], b0[:], w1[:], b1[:] = best_arrays
    float_abs = float_forward(x, w0, b0, w1, b1)
    q_w0, q_b0, q_w1, q_b1 = quantize(w0, b0, w1, b1)
    quant_abs_cp = quant_forward_cp(x, q_w0, q_b0, q_w1, q_b1)

    split_names = (("train", 0), ("validation", 1), ("holdout", 2))
    metrics = {
        name: split_metrics(data, codes == code, float_abs, quant_abs_cp)
        for name, code in split_names
    }
    metadata = {
        "schema_version": 1,
        "architecture": f"absolute768-single-{args.hidden}-screlu-residual-on-v13",
        "feature_count": INPUTS,
        "hidden": args.hidden,
        "qa": QA,
        "qb": QB,
        "cp_scale": CP_SCALE,
        "target_clip_cp": TARGET_CLIP_CP,
        "epochs_requested": args.epochs,
        "best_epoch_by_validation_rmse": best_epoch,
        "best_validation_float_rmse_cp": best_val_rmse,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "weight_decay": args.weight_decay,
        "seed": args.seed,
        "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
        "metrics": metrics,
        "history": history,
    }
    np.savez_compressed(
        args.output_dir / f"student-h{args.hidden}.npz",
        feature_weights=q_w0,
        feature_bias=q_b0,
        output_weights=q_w1,
        output_bias=q_b1,
    )
    (args.output_dir / "training-metadata.json").write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in metadata.items() if k != "history"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
