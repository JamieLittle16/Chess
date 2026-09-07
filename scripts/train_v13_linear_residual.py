#!/usr/bin/env python3
"""Train a tiny king-relative linear correction on top of Little Gambit's V12 evaluator."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import chess
import numpy as np
from scipy import sparse
from sklearn.linear_model import Ridge

FEATURE_COUNT = 24_576
PIECE_VALUE = (0, 100, 320, 335, 500, 900, 0)
PHASE_VALUE = (0, 0, 1, 1, 2, 4, 0)
MAX_PHASE = 24
WHITE = 1


def active_features(board: chess.Board, perspective: bool) -> tuple[int, ...]:
    king = board.king(perspective)
    if king is None:
        raise ValueError("missing perspective king")
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
        features.append(bucket * 12 * 64 + plane * 64 + relative_rank * 8 + file)
    return tuple(features)


def static_bonus(piece: int, square: int, side: int) -> int:
    file = chess.square_file(square)
    raw_rank = chess.square_rank(square)
    rank = raw_rank if side == WHITE else 7 - raw_rank
    distance = abs(2 * file - 7) + abs(2 * rank - 7)
    if piece == chess.PAWN:
        return rank * 9 + (7 - abs(2 * file - 7)) * 2
    if piece == chess.KNIGHT:
        return 36 - 4 * distance
    if piece == chess.BISHOP:
        return 24 - 2 * distance
    if piece == chess.ROOK:
        return rank * 3 + (10 if rank == 6 else 0)
    if piece == chess.QUEEN:
        return 12 - distance
    raise AssertionError(piece)


def king_bonus(square: int, side: int) -> tuple[int, int]:
    file = chess.square_file(square)
    raw_rank = chess.square_rank(square)
    rank = raw_rank if side == WHITE else 7 - raw_rank
    distance = abs(2 * file - 7) + abs(2 * rank - 7)
    castle_file_bonus = max(0, 6 - min(abs(file - 1), abs(file - 6)) * 3)
    middlegame = 28 - rank * 8 + castle_file_bonus - max(0, 10 - distance)
    endgame = 32 - 3 * distance
    return middlegame, endgame


def v12_classical(board: chess.Board) -> int:
    phase = 0
    white_score = 0
    white_bishops = 0
    black_bishops = 0
    white_mg = white_eg = black_mg = black_eg = 0
    for square, piece in board.piece_map().items():
        side = WHITE if piece.color == chess.WHITE else -WHITE
        kind = piece.piece_type
        phase += PHASE_VALUE[kind]
        if kind == chess.KING:
            mg, eg = king_bonus(square, side)
            if side == WHITE:
                white_mg, white_eg = mg, eg
            else:
                black_mg, black_eg = mg, eg
            continue
        value = PIECE_VALUE[kind] + static_bonus(kind, square, side)
        if side == WHITE:
            white_score += value
            white_bishops += kind == chess.BISHOP
        else:
            white_score -= value
            black_bishops += kind == chess.BISHOP

    phase = min(phase, MAX_PHASE)
    white_score += (white_mg * phase + white_eg * (MAX_PHASE - phase)) // MAX_PHASE
    white_score -= (black_mg * phase + black_eg * (MAX_PHASE - phase)) // MAX_PHASE
    if white_bishops >= 2:
        white_score += 28
    if black_bishops >= 2:
        white_score -= 28
    return white_score if board.turn == chess.WHITE else -white_score


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
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-clip-cp", type=float, default=1800.0)
    parser.add_argument("--alphas", default="10,30,100,300,1000,3000,10000")
    parser.add_argument("--clamps", default="80,100,125,150,175,200,250,300,400,600,800,0")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    rows: list[int] = []
    cols: list[int] = []
    vals: list[float] = []
    targets: list[float] = []
    baselines: list[float] = []
    splits: list[str] = []

    with args.teacher.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            cp = record.get("teacher_cp")
            if cp is None:
                continue
            board = chess.Board(record["fen"])
            target = max(-args.target_clip_cp, min(args.target_clip_cp, float(cp)))
            row = len(targets)
            for feature in active_features(board, board.turn):
                rows.append(row)
                cols.append(feature)
                vals.append(1.0)
            for feature in active_features(board, not board.turn):
                rows.append(row)
                cols.append(feature)
                vals.append(-1.0)
            targets.append(target)
            baselines.append(float(v12_classical(board)))
            splits.append(str(record.get("split", "train")))

    count = len(targets)
    matrix = sparse.coo_matrix(
        (np.asarray(vals, dtype=np.float32), (rows, cols)),
        shape=(count, FEATURE_COUNT),
        dtype=np.float32,
    ).tocsr()
    target = np.asarray(targets, dtype=np.float64)
    baseline = np.asarray(baselines, dtype=np.float64)
    residual = target - baseline
    split = np.asarray(splits)
    masks = {name: split == name for name in ("train", "validation", "holdout")}

    trials: list[dict[str, object]] = []
    best: tuple[float, float, Ridge] | None = None
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
        validation_mse = trial["metrics"]["validation"]["mse"]  # type: ignore[index]
        if best is None or float(validation_mse) < best[0]:
            best = (float(validation_mse), alpha, model)

    assert best is not None
    _, selected_alpha, model = best
    float_correction = model.predict(matrix)
    float_prediction = baseline + float_correction

    quantized_weights = np.clip(np.rint(model.coef_), -32768, 32767).astype(np.int16)
    quantized_bias = int(round(float(model.intercept_)))
    quantized_correction = np.asarray(matrix @ quantized_weights.astype(np.float64)).reshape(-1)
    quantized_correction += quantized_bias

    clamp_trials: list[dict[str, object]] = []
    best_clamp: tuple[float, int, np.ndarray] | None = None
    for clamp in [int(value) for value in args.clamps.split(",")]:
        correction = quantized_correction if clamp == 0 else np.clip(quantized_correction, -clamp, clamp)
        prediction = baseline + correction
        trial = {
            "clamp": clamp,
            "metrics": {
                name: metrics(target[mask], prediction[mask]) for name, mask in masks.items()
            },
        }
        clamp_trials.append(trial)
        validation_mse = trial["metrics"]["validation"]["mse"]  # type: ignore[index]
        if best_clamp is None or float(validation_mse) < best_clamp[0]:
            best_clamp = (float(validation_mse), clamp, prediction)

    assert best_clamp is not None
    _, selected_clamp, quantized_prediction = best_clamp

    report = {
        "schema_version": 1,
        "feature_set_id": "king-piece-v1-antisymmetric-v12-residual",
        "records": count,
        "teacher_sha256": hashlib.sha256(args.teacher.read_bytes()).hexdigest(),
        "target_clip_cp": args.target_clip_cp,
        "baseline": {
            name: metrics(target[mask], baseline[mask]) for name, mask in masks.items()
        },
        "ridge_trials": trials,
        "selected_alpha": selected_alpha,
        "float_selected": {
            name: metrics(target[mask], float_prediction[mask]) for name, mask in masks.items()
        },
        "quantization": {
            "kind": "int16-nearest-centipawn",
            "bias_cp": quantized_bias,
            "weight_max_abs": int(np.max(np.abs(quantized_weights.astype(np.int32)))),
            "weight_rms": float(np.sqrt(np.mean(quantized_weights.astype(np.float64) ** 2))),
            "bytes": int(quantized_weights.nbytes),
        },
        "clamp_trials": clamp_trials,
        "selected_clamp_cp": selected_clamp,
        "quantized_selected": {
            name: metrics(target[mask], quantized_prediction[mask]) for name, mask in masks.items()
        },
    }

    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    quantized_weights.astype("<i2").tofile(args.output_dir / "weights.i16")
    (args.output_dir / "model.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "feature_count": FEATURE_COUNT,
                "bias_cp": quantized_bias,
                "clamp_cp": selected_clamp,
                "selected_alpha": selected_alpha,
                "weights": "weights.i16",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
