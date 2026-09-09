#!/usr/bin/env python3
"""Train zero-runtime-cost H64 output-head corrections from shallow Rust search values.

The existing V14 feature transformer, hidden bias, output bias, V13 prefix and runtime arithmetic are
frozen exactly. We only allow small integer changes to the existing 64 output weights. The target is
*not* Rust's absolute score: it is the current Python score plus a conservative fraction of the
clipped difference between Rust's 2k-node search value and its own Gestalt static value. This makes
the teacher a tactical/search correction while preserving the positional calibration already in V14.
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


def trunc_div(v: np.ndarray | int, d: int):
    a = np.asarray(v, dtype=np.int64)
    out = np.where(a >= 0, a // d, -((-a) // d))
    return int(out) if out.ndim == 0 else out


def exact_student(x2: np.ndarray, w: np.ndarray, bias: int, sign: np.ndarray) -> np.ndarray:
    raw = x2.astype(np.int64) @ w.astype(np.int64)
    scaled = trunc_div(raw, QA) + int(bias)
    white = trunc_div(scaled * CP_SCALE, QA * QB)
    signed = white * sign.astype(np.int64)
    return trunc_div(signed, STUDENT_DEN).astype(np.int32)


def metrics(base: np.ndarray, pred: np.ndarray, desired: np.ndarray, idx: np.ndarray) -> dict[str, float]:
    d = pred[idx].astype(np.float64) - desired[idx].astype(np.float64)
    shift = pred[idx].astype(np.float64) - base[idx].astype(np.float64)
    return {
        "rmse_to_desired": float(np.sqrt(np.mean(d * d))),
        "mae_to_desired": float(np.mean(np.abs(d))),
        "mean_abs_shift_cp": float(np.mean(np.abs(shift))),
        "p95_abs_shift_cp": float(np.quantile(np.abs(shift), 0.95)),
        "mean_shift_cp": float(np.mean(shift)),
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=False)

    rows = [json.loads(x) for x in a.corpus.read_text().splitlines() if x.strip()]
    if not rows:
        raise SystemExit("empty corpus")

    sys.path.insert(0, str(a.engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import (
        EVAL_WIDTH,
        STUDENT_OFFSET,
        _build_eval_state_into,
        _evaluate_state,
        _evaluate_state_v13_only,
    )

    model_path = a.engine_dir / "experiments/v14_student_h64.npz"
    model = np.load(model_path, allow_pickle=False)
    fw = np.ascontiguousarray(model["feature_weights"], dtype=np.int16)
    fb = np.ascontiguousarray(model["feature_bias"], dtype=np.int16)
    w0 = np.ascontiguousarray(model["output_weights"], dtype=np.int16)
    bias = int(np.asarray(model["output_bias"]).reshape(-1)[0])
    if fw.shape != (768, 64) or fb.shape != (64,) or w0.shape != (64,):
        raise ValueError("unexpected V14 H64 model topology")

    n = len(rows)
    x2 = np.empty((n, 64), np.int32)
    v13 = np.empty(n, np.int32)
    base = np.empty(n, np.int32)
    sign = np.empty(n, np.int8)
    for i, r in enumerate(rows):
        board = chess.Board(r["fen"])
        enc = encode_position(board)
        st = np.empty(EVAL_WIDTH, np.int32)
        _build_eval_state_into(enc.board, st)
        act = np.clip(st[STUDENT_OFFSET : STUDENT_OFFSET + 64], 0, QA).astype(np.int32)
        x2[i] = act * act
        v13[i] = int(_evaluate_state_v13_only(enc.side, st))
        base[i] = int(_evaluate_state(enc.side, st))
        sign[i] = 1 if board.turn == chess.WHITE else -1
        if (i + 1) % 2000 == 0:
            print(json.dumps({"encoded": i + 1, "records": n}), flush=True)

    reconstructed = v13 + exact_student(x2, w0, bias, sign)
    mismatch = int(np.max(np.abs(reconstructed - base)))
    if mismatch != 0:
        raise AssertionError(f"baseline reconstruction mismatch {mismatch}")

    split = np.asarray([r["split"] for r in rows])
    tr = np.flatnonzero(split == "train")
    va = np.flatnonzero(split == "validation")
    ho = np.flatnonzero(split == "holdout")
    if min(len(tr), len(va), len(ho)) == 0:
        raise ValueError("train/validation/holdout split missing")

    rust = np.asarray([r["rust_search_cp"] for r in rows], np.float64)
    static = np.asarray([r["gestalt_static_cp"] for r in rows], np.float64)
    raw_delta = rust - static
    clipped_delta = np.clip(raw_delta, -300.0, 300.0)
    kinds = np.asarray([r["kind"] for r in rows])

    # Stable qsearch positions are an explicit anchor: Rust search and static Gestalt already agree
    # closely there, so they get extra mass in the regression and discourage global drift.
    sample_weight = np.ones(n, np.float64)
    sample_weight[kinds == "qstable"] = 3.0
    sample_weight[kinds == "qstand"] = 1.25
    sample_weight[kinds == "rfp"] = 1.25
    sample_weight[kinds == "qceil"] = 1.25

    coeff = CP_SCALE / (QA * QA * QB * STUDENT_DEN)
    X = x2.astype(np.float64) * coeff * sign[:, None].astype(np.float64)

    presets = [
        {"name": "c025b1", "fraction": 0.025, "max_step": 1},
        {"name": "c050b2", "fraction": 0.050, "max_step": 2},
        {"name": "c100b2", "fraction": 0.100, "max_step": 2},
    ]
    ridge_scales = (0.03, 0.1, 0.3, 1.0, 3.0, 10.0)
    summary: dict[str, object] = {
        "schema": "v16-shallow-rust-search-h64-head-v1",
        "records": n,
        "split_counts": {s: int(np.sum(split == s)) for s in ("train", "validation", "holdout")},
        "kind_counts": {k: int(np.sum(kinds == k)) for k in sorted(set(kinds.tolist()))},
        "corpus_sha256": hashlib.sha256(a.corpus.read_bytes()).hexdigest(),
        "source_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "raw_search_minus_static": {
            "mean_cp": float(np.mean(raw_delta)),
            "median_cp": float(np.median(raw_delta)),
            "mae_cp": float(np.mean(np.abs(raw_delta))),
            "p95_abs_cp": float(np.quantile(np.abs(raw_delta), 0.95)),
        },
        "presets": [],
    }

    for spec in presets:
        fraction = float(spec["fraction"])
        max_step = int(spec["max_step"])
        desired = base.astype(np.float64) + fraction * clipped_delta
        # Fit the desired full score by solving for the student head around the existing quantised
        # head. The final runtime score is always recomputed with exact integer arithmetic.
        target_student = desired - v13.astype(np.float64)
        Xt = X[tr]
        yt = target_student[tr]
        wt = sample_weight[tr]
        sw = np.sqrt(wt)
        Xw = Xt * sw[:, None]
        yw = yt * sw
        gram = Xw.T @ Xw
        rhs = Xw.T @ yw
        diag = float(np.mean(np.diag(gram)))
        eye = np.eye(64)
        candidates = []
        for rs in ridge_scales:
            lam = max(1e-9, rs * diag)
            fitted = np.linalg.solve(gram + lam * eye, rhs + lam * w0.astype(np.float64))
            lo = w0.astype(np.int32) - max_step
            hi = w0.astype(np.int32) + max_step
            qw = np.clip(np.rint(fitted).astype(np.int32), lo, hi).astype(np.int16)
            pred = v13 + exact_student(x2, qw, bias, sign)
            vm = metrics(base, pred, desired, va)
            hm = metrics(base, pred, desired, ho)
            # Prefer the requested correction, but penalize gratuitous drift strongly. This is
            # intentionally conservative because game strength, not offline fit, is the gate.
            key = vm["mae_to_desired"] + 0.35 * vm["mean_abs_shift_cp"] + 0.05 * vm["p95_abs_shift_cp"]
            candidates.append((key, rs, qw, vm, hm))
        key, rs, qw, vm, hm = min(candidates, key=lambda x: x[0])
        pred = v13 + exact_student(x2, qw, bias, sign)
        path = a.output_dir / f"shallow-search-head-{spec['name']}.npz"
        np.savez_compressed(
            path,
            feature_weights=fw,
            feature_bias=fb,
            output_weights=qw,
            output_bias=np.asarray([bias], np.int32),
        )
        delta_w = qw.astype(np.int32) - w0.astype(np.int32)
        entry = {
            **spec,
            "ridge_scale": rs,
            "validation": vm,
            "holdout": hm,
            "changed_lanes": int(np.count_nonzero(delta_w)),
            "max_abs_weight_step": int(np.max(np.abs(delta_w))),
            "weight_delta": delta_w.tolist(),
            "holdout_qstable": metrics(base, pred, desired, ho[kinds[ho] == "qstable"]),
            "holdout_tactical": metrics(base, pred, desired, ho[kinds[ho] != "qstable"]),
        }
        summary["presets"].append(entry)
        print("MODEL " + json.dumps(entry, sort_keys=True), flush=True)

    (a.output_dir / "metadata.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("FINAL " + json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
