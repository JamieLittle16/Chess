#!/usr/bin/env python3
"""Train a tiny dynamic correction on top of V12 + a blended king-relative residual.

The linear king-piece residual is intentionally incapable of representing several interactions that
Round 57 exposed (rook mobility/penetration, connected rooks, king-zone pressure and pawn shelter).
This script measures a compact set of such interactions, fits only the remaining Stockfish residual,
and exports a tiny fixed-point model suitable for a leaf-only Numba evaluator.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import chess
import numpy as np
from sklearn.linear_model import Ridge

from train_v13_linear_residual import active_features, v12_classical

FEATURE_NAMES = (
    "rook_mobility",
    "bishop_mobility",
    "knight_mobility",
    "queen_mobility",
    "rook_open_files",
    "rook_semi_open_files",
    "rook_seventh",
    "rook_advanced",
    "connected_rooks",
    "rook_king_zone_attacks",
    "queen_king_zone_attacks",
    "king_shield",
    "king_closed_files",
    "isolated_pawns_quality",
    "doubled_pawns_quality",
    "passed_pawns",
)
Q = 16


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--linear-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--target-clip-cp", type=float, default=1800.0)
    parser.add_argument("--linear-scales", default="0,0.25,0.5,0.75,1")
    parser.add_argument("--alphas", default="0.1,0.3,1,3,10,30,100,300,1000")
    parser.add_argument("--clamps", default="40,60,80,100,125,150,200,300,0")
    return parser.parse_args()


def linear_correction(board: chess.Board, weights: np.ndarray, bias: int, clamp: int) -> int:
    correction = bias
    for feature in active_features(board, board.turn):
        correction += int(weights[feature])
    for feature in active_features(board, not board.turn):
        correction -= int(weights[feature])
    if clamp > 0:
        correction = max(-clamp, min(clamp, correction))
    return correction


def king_zone(board: chess.Board, color: bool) -> int:
    king = board.king(color)
    if king is None:
        return 0
    mask = chess.BB_SQUARES[king]
    mask |= int(board.attacks(king))
    return mask


def file_has_pawn(board: chess.Board, file: int, color: bool | None) -> bool:
    mask = chess.BB_FILES[file] & board.pawns
    if color is not None:
        mask &= board.occupied_co[color]
    return bool(mask)


def pawn_structure(board: chess.Board, color: bool) -> tuple[int, int, int]:
    pawns = list(board.pieces(chess.PAWN, color))
    files = [0] * 8
    for sq in pawns:
        files[chess.square_file(sq)] += 1

    isolated = 0
    doubled = 0
    passed = 0
    enemy_pawns = board.pieces(chess.PAWN, not color)
    for file, count in enumerate(files):
        if count > 0 and (file == 0 or files[file - 1] == 0) and (file == 7 or files[file + 1] == 0):
            isolated += count
        if count > 1:
            doubled += count - 1

    for sq in pawns:
        file = chess.square_file(sq)
        rank = chess.square_rank(sq)
        is_passed = True
        for ef in range(max(0, file - 1), min(7, file + 1) + 1):
            for ep in enemy_pawns & chess.BB_FILES[ef]:
                er = chess.square_rank(ep)
                if (color == chess.WHITE and er > rank) or (color == chess.BLACK and er < rank):
                    is_passed = False
                    break
            if not is_passed:
                break
        passed += int(is_passed)
    return isolated, doubled, passed


def side_dynamic(board: chess.Board, color: bool) -> np.ndarray:
    values = np.zeros(len(FEATURE_NAMES), dtype=np.float64)
    enemy_king_zone = king_zone(board, not color)

    rooks = list(board.pieces(chess.ROOK, color))
    bishops = list(board.pieces(chess.BISHOP, color))
    knights = list(board.pieces(chess.KNIGHT, color))
    queens = list(board.pieces(chess.QUEEN, color))

    for sq in rooks:
        attacks = int(board.attacks(sq))
        values[0] += attacks.bit_count()
        file = chess.square_file(sq)
        own_pawn = file_has_pawn(board, file, color)
        any_pawn = file_has_pawn(board, file, None)
        values[4] += int(not any_pawn)
        values[5] += int(not own_pawn and any_pawn)
        relative_rank = chess.square_rank(sq) if color == chess.WHITE else 7 - chess.square_rank(sq)
        values[6] += int(relative_rank == 6)
        values[7] += int(relative_rank >= 4)
        values[9] += (attacks & enemy_king_zone).bit_count()

    for sq in bishops:
        values[1] += int(board.attacks(sq)).bit_count()
    for sq in knights:
        values[2] += int(board.attacks(sq)).bit_count()
    for sq in queens:
        attacks = int(board.attacks(sq))
        values[3] += attacks.bit_count()
        values[10] += (attacks & enemy_king_zone).bit_count()

    if len(rooks) >= 2:
        connected = 0
        for i, left in enumerate(rooks):
            attacks = int(board.attacks(left))
            for right in rooks[i + 1 :]:
                connected += int(bool(attacks & chess.BB_SQUARES[right]))
        values[8] = connected

    king = board.king(color)
    if king is not None:
        kf = chess.square_file(king)
        kr = chess.square_rank(king)
        direction = 1 if color == chess.WHITE else -1
        shield = 0
        closed = 0
        for file in range(max(0, kf - 1), min(7, kf + 1) + 1):
            closed += int(file_has_pawn(board, file, color))
            for distance in (1, 2):
                rank = kr + direction * distance
                if 0 <= rank < 8:
                    sq = chess.square(file, rank)
                    shield += int(board.piece_type_at(sq) == chess.PAWN and board.color_at(sq) == color)
        values[11] = shield
        values[12] = closed

    isolated, doubled, passed = pawn_structure(board, color)
    values[13] = -isolated
    values[14] = -doubled
    values[15] = passed
    return values


def dynamic_features(board: chess.Board) -> np.ndarray:
    us = board.turn
    return side_dynamic(board, us) - side_dynamic(board, not us)


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
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    linear_model = json.loads((args.linear_dir / "model.json").read_text())
    linear_weights = np.fromfile(args.linear_dir / linear_model["weights"], dtype="<i2")
    linear_bias = int(linear_model["bias_cp"])
    linear_clamp = int(linear_model["clamp_cp"])

    targets: list[float] = []
    classical: list[float] = []
    linear: list[float] = []
    features: list[np.ndarray] = []
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
            targets.append(max(-args.target_clip_cp, min(args.target_clip_cp, float(cp))))
            classical.append(float(v12_classical(board)))
            linear.append(float(linear_correction(board, linear_weights, linear_bias, linear_clamp)))
            features.append(dynamic_features(board))
            splits.append(str(record.get("split", "train")))

    target = np.asarray(targets, dtype=np.float64)
    classical_array = np.asarray(classical, dtype=np.float64)
    linear_array = np.asarray(linear, dtype=np.float64)
    matrix = np.vstack(features)
    split = np.asarray(splits)
    masks = {name: split == name for name in ("train", "validation", "holdout")}

    train = masks["train"]
    mean = matrix[train].mean(axis=0)
    std = matrix[train].std(axis=0)
    std[std < 1e-9] = 1.0
    normalized = (matrix - mean) / std

    scales = [float(value) for value in args.linear_scales.split(",")]
    alphas = [float(value) for value in args.alphas.split(",")]
    clamps = [int(value) for value in args.clamps.split(",")]
    trials: list[dict[str, object]] = []
    selected: tuple[float, float, float, Ridge, np.ndarray, np.ndarray] | None = None

    for scale in scales:
        base = classical_array + np.floor(linear_array * scale)
        residual = target - base
        for alpha in alphas:
            model = Ridge(alpha=alpha, fit_intercept=True, solver="lsqr", tol=1e-8, max_iter=5000)
            model.fit(normalized[train], residual[train])
            coef_raw = model.coef_ / std
            intercept_raw = float(model.intercept_ - np.dot(model.coef_, mean / std))
            correction = matrix @ coef_raw + intercept_raw
            prediction = base + correction
            validation_mse = metrics(target[masks["validation"]], prediction[masks["validation"]])["mse"]
            trial = {
                "linear_scale": scale,
                "alpha": alpha,
                "coef_raw": {name: float(value) for name, value in zip(FEATURE_NAMES, coef_raw)},
                "metrics": {name: metrics(target[mask], prediction[mask]) for name, mask in masks.items()},
            }
            trials.append(trial)
            score = float(validation_mse)
            if selected is None or score < selected[0]:
                selected = (score, scale, alpha, model, coef_raw, base)

    assert selected is not None
    _, selected_scale, selected_alpha, selected_model, coef_raw, base = selected
    intercept_raw = float(selected_model.intercept_ - np.dot(selected_model.coef_, mean / std))

    weights_q = np.rint(coef_raw * Q).astype(np.int16)
    bias_q = int(round(intercept_raw * Q))
    correction_q = (matrix @ weights_q.astype(np.float64) + bias_q) / Q

    clamp_trials: list[dict[str, object]] = []
    best_clamp: tuple[float, int, np.ndarray] | None = None
    for clamp in clamps:
        correction = correction_q if clamp == 0 else np.clip(correction_q, -clamp, clamp)
        prediction = base + correction
        trial = {
            "clamp_cp": clamp,
            "metrics": {name: metrics(target[mask], prediction[mask]) for name, mask in masks.items()},
        }
        clamp_trials.append(trial)
        score = float(trial["metrics"]["validation"]["mse"])  # type: ignore[index]
        if best_clamp is None or score < best_clamp[0]:
            best_clamp = (score, clamp, prediction)

    assert best_clamp is not None
    _, selected_clamp, final_prediction = best_clamp
    classical_metrics = {name: metrics(target[mask], classical_array[mask]) for name, mask in masks.items()}
    blend_base = classical_array + np.floor(linear_array * selected_scale)
    blend_metrics = {name: metrics(target[mask], blend_base[mask]) for name, mask in masks.items()}
    final_metrics = {name: metrics(target[mask], final_prediction[mask]) for name, mask in masks.items()}

    model_json = {
        "schema_version": 1,
        "feature_names": FEATURE_NAMES,
        "linear_scale": selected_scale,
        "linear_bias_cp": linear_bias,
        "linear_clamp_cp": linear_clamp,
        "dynamic_q": Q,
        "dynamic_bias_q": bias_q,
        "dynamic_weights_q": [int(value) for value in weights_q],
        "dynamic_clamp_cp": selected_clamp,
        "selected_alpha": selected_alpha,
    }
    report = {
        "schema_version": 1,
        "records": len(target),
        "feature_names": FEATURE_NAMES,
        "classical": classical_metrics,
        "selected_blend_before_dynamic": blend_metrics,
        "selected_final": final_metrics,
        "selection": model_json,
        "trials": trials,
        "clamp_trials": clamp_trials,
    }
    (args.output_dir / "model.json").write_text(json.dumps(model_json, indent=2, sort_keys=True) + "\n")
    (args.output_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"model": model_json, "classical": classical_metrics, "blend": blend_metrics, "final": final_metrics}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
