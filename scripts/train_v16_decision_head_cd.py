#!/usr/bin/env python3
"""Directly optimise V14's existing quantised H64 output head for alpha/beta decisions.

This is the deliberately discrete counterpart to train_v16_decision_head.py.  The feature
transformer, hidden activations, output bias, scaling and runtime topology remain byte-for-byte
unchanged; only the 64 int16 output weights may move inside a tiny box around the production head.
Coordinate descent evaluates the *exact quantised runtime score* and accepts a one-step move only
when it reduces weighted alpha/beta classification error on the training split.  Validation and
holdout records are never used to choose coordinate moves.
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
STUDENT_DEN = 12
MATE_THRESHOLD = 30_000


def trunc_div(v: np.ndarray | int, d: int):
    a = np.asarray(v, dtype=np.int64)
    out = np.where(a >= 0, a // d, -((-a) // d))
    return int(out) if out.ndim == 0 else out


def load_engine(directory: Path):
    sys.path.insert(0, str(directory.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import (
        EVAL_WIDTH,
        STUDENT_OFFSET,
        _build_eval_state_into,
        _evaluate_state,
        _evaluate_state_v13_only,
    )
    return (
        encode_position,
        EVAL_WIDTH,
        STUDENT_OFFSET,
        _build_eval_state_into,
        _evaluate_state,
        _evaluate_state_v13_only,
    )


def student_from_raw(raw: np.ndarray, bias: int, sign: np.ndarray) -> np.ndarray:
    scaled = trunc_div(raw, QA) + int(bias)
    white = trunc_div(scaled * CP_SCALE, QA * QB)
    return trunc_div(white * sign.astype(np.int64), STUDENT_DEN).astype(np.int32)


def decision_metrics(rows: list[dict], idx: np.ndarray, pred: np.ndarray) -> dict[str, float | int]:
    teacher = np.asarray([rows[i]["teacher_cp"] for i in idx], np.int32)
    alpha = np.asarray([rows[i]["alpha"] for i in idx], np.int32)
    beta = np.asarray([rows[i]["beta"] for i in idx], np.int32)
    p = pred[idx]
    out: dict[str, float | int] = {}
    for name, threshold, strict in (("beta", beta, False), ("alpha", alpha, True)):
        finite = np.abs(threshold) < MATE_THRESHOLD
        truth = (teacher > threshold) if strict else (teacher >= threshold)
        got = (p > threshold) if strict else (p >= threshold)
        out[f"{name}_agreement"] = float(np.mean(truth[finite] == got[finite])) if finite.any() else 1.0
        near = finite & (np.abs(teacher - threshold) <= 150)
        out[f"{name}_near_records"] = int(near.sum())
        out[f"{name}_near_agreement"] = float(np.mean(truth[near] == got[near])) if near.any() else 1.0
    diff = p.astype(np.float64) - teacher.astype(np.float64)
    out["rmse_cp"] = float(np.sqrt(np.mean(diff * diff)))
    out["mae_cp"] = float(np.mean(np.abs(diff)))
    return out


def metric_key(m: dict[str, float | int]) -> float:
    return (
        5.0 * (1.0 - float(m["beta_near_agreement"]))
        + 2.5 * (1.0 - float(m["alpha_near_agreement"]))
        + 1.0 * (1.0 - float(m["beta_agreement"]))
        + 0.5 * (1.0 - float(m["alpha_agreement"]))
        + 0.00002 * float(m["rmse_cp"])
    )


def training_loss(
    pred: np.ndarray,
    teacher: np.ndarray,
    alpha: np.ndarray,
    beta: np.ndarray,
    kind_weight: np.ndarray,
) -> float:
    finite_b = np.abs(beta) < MATE_THRESHOLD
    finite_a = np.abs(alpha) < MATE_THRESHOLD
    # Search-sensitive mass is concentrated close to the live windows, especially beta cutoffs.
    wb = kind_weight * (1.0 + 10.0 * np.exp(-np.abs(teacher - beta) / 90.0))
    wa = kind_weight * (1.0 + 5.0 * np.exp(-np.abs(teacher - alpha) / 110.0))
    truth_b = teacher >= beta
    pred_b = pred >= beta
    truth_a = teacher > alpha
    pred_a = pred > alpha
    loss_b = float(np.sum(wb[finite_b] * (truth_b[finite_b] != pred_b[finite_b])) / np.sum(wb[finite_b]))
    loss_a = float(np.sum(wa[finite_a] * (truth_a[finite_a] != pred_a[finite_a])) / np.sum(wa[finite_a]))
    # A very small calibration term breaks exact classification ties without turning this back into
    # a centipawn-regression objective.
    mae = float(np.mean(np.minimum(np.abs(pred.astype(np.float64) - teacher), 600.0)))
    return 1.35 * loss_b + 0.65 * loss_a + 0.000002 * mae


def optimise_bound(
    bound: int,
    x2: np.ndarray,
    v13: np.ndarray,
    sign: np.ndarray,
    w0: np.ndarray,
    bias: int,
    train: np.ndarray,
    teacher: np.ndarray,
    alpha: np.ndarray,
    beta: np.ndarray,
    kind_weight: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[dict[str, float | int]]]:
    weights = w0.astype(np.int32).copy()
    raw = x2.astype(np.int64) @ weights.astype(np.int64)
    lo = w0.astype(np.int32) - bound
    hi = w0.astype(np.int32) + bound
    trace: list[dict[str, float | int]] = []

    def pred_for(raw_values: np.ndarray) -> np.ndarray:
        return v13 + student_from_raw(raw_values, bias, sign)

    current_pred = pred_for(raw)
    current = training_loss(
        current_pred[train], teacher[train], alpha[train], beta[train], kind_weight[train]
    )
    trace.append({"pass": 0, "loss": current, "accepted": 0})
    max_passes = 2 * bound + 4
    for pass_index in range(1, max_passes + 1):
        accepted = 0
        order = range(64) if pass_index % 2 else range(63, -1, -1)
        for lane in order:
            best_loss = current
            best_delta = 0
            column = x2[:, lane].astype(np.int64)
            for delta in (-1, 1):
                proposed = int(weights[lane]) + delta
                if proposed < int(lo[lane]) or proposed > int(hi[lane]):
                    continue
                trial_raw_train = raw[train] + delta * column[train]
                trial_pred_train = v13[train] + student_from_raw(
                    trial_raw_train, bias, sign[train]
                )
                trial_loss = training_loss(
                    trial_pred_train,
                    teacher[train],
                    alpha[train],
                    beta[train],
                    kind_weight[train],
                )
                if trial_loss < best_loss - 1e-10:
                    best_loss = trial_loss
                    best_delta = delta
            if best_delta:
                weights[lane] += best_delta
                raw += best_delta * column
                current = best_loss
                accepted += 1
        trace.append({"pass": pass_index, "loss": current, "accepted": accepted})
        print(json.dumps({"bound": bound, **trace[-1]}), flush=True)
        if accepted == 0:
            break
    return weights.astype(np.int16), pred_for(raw), trace


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", type=Path, required=True)
    ap.add_argument("--engine-dir", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--max-records", type=int, default=180_000)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    rows = [json.loads(line) for line in args.corpus.read_text().splitlines() if line.strip()]
    if len(rows) > args.max_records:
        step = len(rows) / args.max_records
        rows = [rows[int(i * step)] for i in range(args.max_records)]

    enc, width, off, build, full, v13_fn = load_engine(args.engine_dir)
    model_path = args.engine_dir / "experiments/v14_student_h64.npz"
    model = np.load(model_path, allow_pickle=False)
    fw = np.ascontiguousarray(model["feature_weights"], dtype=np.int16)
    fb = np.ascontiguousarray(model["feature_bias"], dtype=np.int16)
    w0 = np.ascontiguousarray(model["output_weights"], dtype=np.int16)
    bias = int(np.asarray(model["output_bias"]).reshape(-1)[0])
    if fw.shape != (768, 64) or fb.shape != (64,) or w0.shape != (64,):
        raise ValueError("unexpected V14 H64 model")

    n = len(rows)
    x2 = np.empty((n, 64), np.int32)
    v13 = np.empty(n, np.int32)
    base = np.empty(n, np.int32)
    sign = np.empty(n, np.int8)
    for i, row in enumerate(rows):
        board = chess.Board(row["fen"])
        encoded = enc(board)
        state = np.empty(width, np.int32)
        build(encoded.board, state)
        act = np.clip(state[off : off + 64], 0, QA).astype(np.int32)
        x2[i] = act * act
        v13[i] = int(v13_fn(encoded.side, state))
        base[i] = int(full(encoded.side, state))
        sign[i] = 1 if board.turn == chess.WHITE else -1
        if (i + 1) % 20_000 == 0:
            print(json.dumps({"encoded": i + 1, "records": n}), flush=True)

    base_raw = x2.astype(np.int64) @ w0.astype(np.int64)
    reconstructed = v13 + student_from_raw(base_raw, bias, sign)
    mismatch = int(np.max(np.abs(reconstructed - base)))
    if mismatch != 0:
        raise AssertionError(f"exact baseline reconstruction mismatch {mismatch}")

    split = np.asarray([row["split"] for row in rows])
    tr = np.flatnonzero(split == "train")
    va = np.flatnonzero(split == "validation")
    ho = np.flatnonzero(split == "holdout")
    teacher = np.asarray([row["teacher_cp"] for row in rows], np.float64)
    alpha = np.asarray([row["alpha"] for row in rows], np.float64)
    beta = np.asarray([row["beta"] for row in rows], np.float64)
    kind = np.asarray([row["kind"] for row in rows])
    kind_map = {"rfp": 3.0, "qstand": 2.0, "qstable": 1.0, "qceil": 1.25, "qpath": 1.0}
    kind_weight = np.asarray([kind_map[k] for k in kind], np.float64)

    baseline = {
        "validation": decision_metrics(rows, va, base),
        "holdout": decision_metrics(rows, ho, base),
    }
    print("BASELINE", json.dumps(baseline, sort_keys=True), flush=True)

    candidates = []
    for bound in (1, 2, 3):
        weights, pred, trace = optimise_bound(
            bound, x2, v13, sign, w0, bias, tr, teacher, alpha, beta, kind_weight
        )
        vm = decision_metrics(rows, va, pred)
        hm = decision_metrics(rows, ho, pred)
        delta = weights.astype(np.int32) - w0.astype(np.int32)
        item = {
            "bound": bound,
            "validation": vm,
            "holdout": hm,
            "metric_key": metric_key(vm),
            "mean_abs_shift_cp": float(np.mean(np.abs(pred.astype(np.float64) - base))),
            "changed_lanes": int(np.count_nonzero(delta)),
            "max_abs_step": int(np.max(np.abs(delta))),
            "trace": trace,
            "delta": delta.tolist(),
        }
        candidates.append(item)
        np.savez_compressed(
            args.output_dir / f"decision-head-cd-bound{bound}.npz",
            feature_weights=fw,
            feature_bias=fb,
            output_weights=weights,
            output_bias=np.asarray([bias], np.int32),
        )
        print("CANDIDATE", json.dumps(item, sort_keys=True), flush=True)

    best = min(candidates, key=lambda item: float(item["metric_key"]))
    best_model = args.output_dir / f"decision-head-cd-bound{best['bound']}.npz"
    loaded = np.load(best_model, allow_pickle=False)
    np.savez_compressed(
        args.output_dir / "decision-head-cd-best.npz",
        feature_weights=loaded["feature_weights"],
        feature_bias=loaded["feature_bias"],
        output_weights=loaded["output_weights"],
        output_bias=loaded["output_bias"],
    )
    meta = {
        "schema": "v16-decision-aware-h64-coordinate-v1",
        "records": n,
        "split_counts": {s: int(np.sum(split == s)) for s in ("train", "validation", "holdout")},
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "source_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "baseline": baseline,
        "candidates": candidates,
        "best_bound": int(best["bound"]),
    }
    (args.output_dir / "metadata.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps(meta, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
