#!/usr/bin/env python3
"""Fine-tune the existing V14 H64 feature transformer on shallow Rust-search corrections.

Runtime topology is unchanged. The 64 output weights, output bias, V13 prefix and inference code are
frozen. We learn a small float delta for the existing 768x64 piece-square feature matrix using a
linearisation around V14, then quantise that delta to bounded integer steps and select only by a
held-out split using exact integer inference. Stable qsearch positions are weighted as anchors.
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


def exact_student_from_hidden(hidden: np.ndarray, ow: np.ndarray, ob: int, sign: np.ndarray) -> np.ndarray:
    act = np.clip(hidden.astype(np.int64), 0, QA)
    raw = (act * act) @ ow.astype(np.int64)
    scaled = trunc_div(raw, QA) + int(ob)
    white = trunc_div(scaled * CP_SCALE, QA * QB)
    return trunc_div(white * sign.astype(np.int64), STUDENT_DEN).astype(np.int32)


def metric(base: np.ndarray, pred: np.ndarray, desired: np.ndarray, idx: np.ndarray) -> dict[str, float]:
    if len(idx) == 0:
        return {"mae_to_desired": 0.0, "rmse_to_desired": 0.0, "mean_abs_shift_cp": 0.0,
                "p95_abs_shift_cp": 0.0, "mean_shift_cp": 0.0}
    e = pred[idx].astype(np.float64) - desired[idx].astype(np.float64)
    s = pred[idx].astype(np.float64) - base[idx].astype(np.float64)
    return {
        "mae_to_desired": float(np.mean(np.abs(e))),
        "rmse_to_desired": float(np.sqrt(np.mean(e * e))),
        "mean_abs_shift_cp": float(np.mean(np.abs(s))),
        "p95_abs_shift_cp": float(np.quantile(np.abs(s), 0.95)),
        "mean_shift_cp": float(np.mean(s)),
    }


def feature_index(signed_piece: int, square: int) -> int:
    return (0 if signed_piece > 0 else 384) + (abs(signed_piece) - 1) * 64 + square


def optimise_linearised(B: np.ndarray, G: np.ndarray, y: np.ndarray, weight: np.ndarray,
                        bound: float, iterations: int = 180) -> np.ndarray:
    """Weighted Adam on the linearised score correction, with a small L2 anchor at zero."""
    D = np.zeros((768, 64), np.float32)
    m = np.zeros_like(D)
    v = np.zeros_like(D)
    Btr = B.astype(np.float32, copy=False)
    Gtr = G.astype(np.float32, copy=False)
    ytr = y.astype(np.float32, copy=False)
    w = weight.astype(np.float32, copy=False)
    denom = float(max(1.0, np.sum(w)))
    lr = 0.06
    l2 = 0.015
    for it in range(1, iterations + 1):
        hidden_delta = Btr @ D
        pred = np.sum(hidden_delta * Gtr, axis=1)
        errw = (pred - ytr) * w
        grad = (Btr.T @ (errw[:, None] * Gtr)) / denom + l2 * D
        m = 0.9 * m + 0.1 * grad
        v = 0.999 * v + 0.001 * (grad * grad)
        mhat = m / (1.0 - 0.9**it)
        vhat = v / (1.0 - 0.999**it)
        D -= lr * mhat / (np.sqrt(vhat) + 1e-6)
        np.clip(D, -bound, bound, out=D)
        if it % 30 == 0:
            loss = float(np.sum(w * (pred - ytr) ** 2) / denom)
            print(json.dumps({"iter": it, "linearised_weighted_mse": loss,
                              "mean_abs_delta": float(np.mean(np.abs(D))),
                              "max_abs_delta": float(np.max(np.abs(D)))}), flush=True)
    return D


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--engine-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    a = p.parse_args()
    a.output_dir.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(x) for x in a.corpus.read_text().splitlines() if x.strip()]

    sys.path.insert(0, str(a.engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, STUDENT_OFFSET, _build_eval_state_into, _evaluate_state, _evaluate_state_v13_only

    model_path = a.engine_dir / "experiments/v14_student_h64.npz"
    model = np.load(model_path, allow_pickle=False)
    fw0 = np.ascontiguousarray(model["feature_weights"], dtype=np.int16)
    fb = np.ascontiguousarray(model["feature_bias"], dtype=np.int16)
    ow = np.ascontiguousarray(model["output_weights"], dtype=np.int16)
    ob = int(np.asarray(model["output_bias"]).reshape(-1)[0])
    if fw0.shape != (768, 64) or fb.shape != (64,) or ow.shape != (64,):
        raise ValueError("unexpected V14 H64 topology")

    n = len(rows)
    B = np.zeros((n, 768), np.float32)
    hidden0 = np.empty((n, 64), np.int32)
    v13 = np.empty(n, np.int32)
    base = np.empty(n, np.int32)
    sign = np.empty(n, np.int8)
    for i, r in enumerate(rows):
        board = chess.Board(r["fen"])
        enc = encode_position(board)
        st = np.empty(EVAL_WIDTH, np.int32)
        _build_eval_state_into(enc.board, st)
        hidden0[i] = st[STUDENT_OFFSET:STUDENT_OFFSET + 64]
        v13[i] = int(_evaluate_state_v13_only(enc.side, st))
        base[i] = int(_evaluate_state(enc.side, st))
        sign[i] = 1 if board.turn == chess.WHITE else -1
        for sq in range(64):
            pc = int(enc.board[sq])
            if pc:
                B[i, feature_index(pc, sq)] = 1.0
        if (i + 1) % 2000 == 0:
            print(json.dumps({"encoded": i + 1, "records": n}), flush=True)

    rec = v13 + exact_student_from_hidden(hidden0, ow, ob, sign)
    if int(np.max(np.abs(rec - base))) != 0:
        raise AssertionError("exact baseline reconstruction failed")
    rebuilt_hidden = B @ fw0.astype(np.float32) + fb.astype(np.float32)
    if int(np.max(np.abs(np.rint(rebuilt_hidden).astype(np.int32) - hidden0))) != 0:
        raise AssertionError("absolute768 active-feature reconstruction failed")

    split = np.asarray([r["split"] for r in rows])
    kinds = np.asarray([r["kind"] for r in rows])
    tr = np.flatnonzero(split == "train")
    va = np.flatnonzero(split == "validation")
    ho = np.flatnonzero(split == "holdout")
    rust = np.asarray([r["rust_search_cp"] for r in rows], np.float32)
    static = np.asarray([r["gestalt_static_cp"] for r in rows], np.float32)
    teacher_delta = np.clip(rust - static, -300.0, 300.0)

    # Derivative of the side-to-move H64 contribution w.r.t. one hidden-accumulator unit.
    act = np.clip(hidden0.astype(np.float32), 0.0, float(QA))
    live = ((hidden0 > 0) & (hidden0 < QA)).astype(np.float32)
    deriv_scale = 2.0 * CP_SCALE / float(QA * QA * QB * STUDENT_DEN)
    G = sign.astype(np.float32)[:, None] * live * act * ow.astype(np.float32)[None, :] * deriv_scale

    weights = np.ones(n, np.float32)
    weights[kinds == "qstable"] = 3.0
    weights[kinds != "qstable"] = 1.25

    presets = [
        {"name": "f10b1", "fraction": 0.10, "float_bound": 1.25, "int_bound": 1},
        {"name": "f20b1", "fraction": 0.20, "float_bound": 1.50, "int_bound": 1},
        {"name": "f20b2", "fraction": 0.20, "float_bound": 2.25, "int_bound": 2},
    ]
    summary: dict[str, object] = {
        "schema": "v16-shallow-rust-search-h64-feature-finetune-v1",
        "records": n,
        "corpus_sha256": hashlib.sha256(a.corpus.read_bytes()).hexdigest(),
        "source_model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "presets": [],
    }

    for spec in presets:
        frac = float(spec["fraction"])
        y = frac * teacher_delta
        D = optimise_linearised(B[tr], G[tr], y[tr], weights[tr], float(spec["float_bound"]))
        candidates = []
        if int(spec["int_bound"]) == 1:
            for threshold in (0.20, 0.30, 0.40, 0.50, 0.65, 0.80):
                qd = np.zeros_like(D, dtype=np.int16)
                qd[D >= threshold] = 1
                qd[D <= -threshold] = -1
                candidates.append((f"threshold={threshold}", qd))
        else:
            for scale in (0.65, 0.80, 1.00, 1.20):
                qd = np.clip(np.rint(D * scale), -2, 2).astype(np.int16)
                candidates.append((f"scale={scale}", qd))

        desired = base.astype(np.float64) + y.astype(np.float64)
        scored = []
        for label, qd in candidates:
            hidden = hidden0 + np.rint(B @ qd.astype(np.float32)).astype(np.int32)
            pred = v13 + exact_student_from_hidden(hidden, ow, ob, sign)
            vm = metric(base, pred, desired, va)
            hm = metric(base, pred, desired, ho)
            # Require conservative behaviour: fit the requested correction but charge directly for
            # evaluation drift. The games remain the only strength criterion.
            key = vm["mae_to_desired"] + 0.25 * vm["mean_abs_shift_cp"] + 0.04 * vm["p95_abs_shift_cp"]
            if vm["mean_abs_shift_cp"] > 18.0 or vm["p95_abs_shift_cp"] > 55.0:
                key += 1000.0
            scored.append((key, label, qd, vm, hm, pred))
        _, label, qd, vm, hm, pred = min(scored, key=lambda x: x[0])
        fw = (fw0.astype(np.int32) + qd.astype(np.int32)).astype(np.int16)
        np.savez_compressed(a.output_dir / f"shallow-search-features-{spec['name']}.npz",
                            feature_weights=fw, feature_bias=fb, output_weights=ow,
                            output_bias=np.asarray([ob], np.int32))
        entry = {
            **spec,
            "quantizer": label,
            "changed_feature_weights": int(np.count_nonzero(qd)),
            "changed_feature_rows": int(np.count_nonzero(np.any(qd != 0, axis=1))),
            "max_abs_integer_step": int(np.max(np.abs(qd))),
            "validation": vm,
            "holdout": hm,
            "holdout_qstable": metric(base, pred, desired, ho[kinds[ho] == "qstable"]),
            "holdout_tactical": metric(base, pred, desired, ho[kinds[ho] != "qstable"]),
        }
        summary["presets"].append(entry)
        print("MODEL " + json.dumps(entry, sort_keys=True), flush=True)

    (a.output_dir / "metadata.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print("FINAL " + json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
