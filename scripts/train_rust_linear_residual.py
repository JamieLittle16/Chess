#!/usr/bin/env python3
"""Fit a quantized king-piece-v1 linear residual over the exact Rust classical evaluator."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import chess
import numpy as np
from scipy import sparse
from sklearn.linear_model import Ridge

FEATURE_COUNT = 24_576


def active_features(board: chess.Board, perspective: bool) -> tuple[int, ...]:
    king = board.king(perspective)
    if king is None:
        raise ValueError("position is missing perspective king")
    king_file = chess.square_file(king)
    king_rank = chess.square_rank(king)
    relative_king_rank = king_rank if perspective == chess.WHITE else 7 - king_rank
    mirror_files = king_file >= 4
    canonical_king_file = 7 - king_file if mirror_files else king_file
    bucket = relative_king_rank * 4 + canonical_king_file

    features: list[int] = []
    for square, piece in board.piece_map().items():
        ownership = 0 if piece.color == perspective else 1
        plane = ownership * 6 + (piece.piece_type - 1)
        file = chess.square_file(square)
        rank = chess.square_rank(square)
        relative_rank = rank if perspective == chess.WHITE else 7 - rank
        if mirror_files:
            file = 7 - file
        feature = bucket * 12 * 64 + plane * 64 + relative_rank * 8 + file
        if not 0 <= feature < FEATURE_COUNT:
            raise AssertionError(feature)
        features.append(feature)
    return tuple(features)


def rust_baselines(binary: Path, fens: list[str]) -> np.ndarray:
    payload = "".join(f"{fen}\n" for fen in fens)
    result = subprocess.run(
        [str(binary.resolve())],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
        timeout=max(60, len(fens) // 100),
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Rust eval oracle exited {result.returncode}\nstdout:\n{result.stdout[-2000:]}\n"
            f"stderr:\n{result.stderr[-2000:]}"
        )
    values = [int(line) for line in result.stdout.splitlines() if line.strip()]
    if len(values) != len(fens):
        raise RuntimeError(f"Rust eval oracle returned {len(values)} scores for {len(fens)} FENs")
    return np.asarray(values, dtype=np.float64)


def metrics(target: np.ndarray, prediction: np.ndarray) -> dict[str, float | int | None]:
    if len(target) == 0:
        return {"n": 0}
    error = prediction - target
    return {
        "n": int(len(target)),
        "mse": float(np.mean(error * error)),
        "rmse": float(np.sqrt(np.mean(error * error))),
        "mae": float(np.mean(np.abs(error))),
        "bias": float(np.mean(error)),
        "corr": float(np.corrcoef(target, prediction)[0, 1]) if len(target) > 1 else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--baseline-engine", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-clip-cp", type=float, default=1800.0)
    parser.add_argument("--alphas", default="30,100,300,1000,3000")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    records: list[dict[str, object]] = []
    with args.teacher.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("teacher_cp") is not None:
                records.append(record)
    if not records:
        raise ValueError("teacher corpus contains no usable centipawn records")

    boards = [chess.Board(str(record["fen"])) for record in records]
    fens = [board.fen() for board in boards]
    baseline = rust_baselines(args.baseline_engine, fens)
    target = np.asarray(
        [
            max(-args.target_clip_cp, min(args.target_clip_cp, float(record["teacher_cp"])))
            for record in records
        ],
        dtype=np.float64,
    )
    splits = np.asarray([str(record.get("split", "train")) for record in records])
    masks = {name: splits == name for name in ("train", "validation", "holdout")}
    if not np.any(masks["train"]):
        raise ValueError("teacher corpus has no train split")
    if not np.any(masks["validation"]):
        raise ValueError("teacher corpus has no validation split")

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    for row, board in enumerate(boards):
        for feature in active_features(board, board.turn):
            rows.append(row)
            cols.append(feature)
            vals.append(1.0)
        for feature in active_features(board, not board.turn):
            rows.append(row)
            cols.append(feature)
            vals.append(-1.0)
    matrix = sparse.coo_matrix(
        (np.asarray(vals, dtype=np.float32), (rows, cols)),
        shape=(len(records), FEATURE_COUNT),
        dtype=np.float32,
    ).tocsr()
    residual = target - baseline

    trials: list[dict[str, object]] = []
    selected: tuple[float, float, Ridge] | None = None
    for alpha in [float(value) for value in args.alphas.split(",")]:
        model = Ridge(alpha=alpha, fit_intercept=True, solver="lsqr", tol=1e-5, max_iter=3000)
        model.fit(matrix[masks["train"]], residual[masks["train"]])
        prediction = baseline + model.predict(matrix)
        trial = {
            "alpha": alpha,
            "coef_rms": float(np.sqrt(np.mean(model.coef_ * model.coef_))),
            "coef_max_abs": float(np.max(np.abs(model.coef_))),
            "intercept": float(model.intercept_),
            "metrics": {
                name: metrics(target[mask], prediction[mask]) for name, mask in masks.items()
            },
        }
        trials.append(trial)
        validation_mse = float(trial["metrics"]["validation"]["mse"])  # type: ignore[index]
        if selected is None or validation_mse < selected[0]:
            selected = (validation_mse, alpha, model)

    assert selected is not None
    _, selected_alpha, model = selected
    quantized_weights = np.clip(np.rint(model.coef_), -32768, 32767).astype(np.int16)
    quantized_bias = int(round(float(model.intercept_)))
    correction = np.asarray(matrix @ quantized_weights.astype(np.float64)).reshape(-1)
    correction += quantized_bias
    prediction = baseline + correction

    report = {
        "schema_version": 1,
        "feature_set_id": "king-piece-v1-antisymmetric-rust-classical-residual",
        "records": len(records),
        "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
        "baseline_binary_sha256": hashlib.sha256(args.baseline_engine.read_bytes()).hexdigest(),
        "target_clip_cp": args.target_clip_cp,
        "baseline": {name: metrics(target[mask], baseline[mask]) for name, mask in masks.items()},
        "ridge_trials": trials,
        "selected_alpha": selected_alpha,
        "quantized": {
            "bias_cp": quantized_bias,
            "weight_max_abs": int(np.max(np.abs(quantized_weights.astype(np.int32)))),
            "weight_rms": float(np.sqrt(np.mean(quantized_weights.astype(np.float64) ** 2))),
            "bytes": int(quantized_weights.nbytes),
            "metrics": {name: metrics(target[mask], prediction[mask]) for name, mask in masks.items()},
        },
    }
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    quantized_weights.astype("<i2").tofile(args.output_dir / "weights.i16")
    model_json = {
        "schema_version": 1,
        "feature_count": FEATURE_COUNT,
        "bias_cp": quantized_bias,
        "selected_alpha": selected_alpha,
        "weights": "weights.i16",
    }
    (args.output_dir / "model.json").write_text(json.dumps(model_json, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
