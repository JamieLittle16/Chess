#!/usr/bin/env python3
"""Build a search-leaf teacher that spends drift only on large Rust/V14 disagreements.

The globally blended b050 H64 student replicated a small positive game signal while moving only a
few centipawns from V14 on ordinary positions.  This teacher keeps that search-compatible bias:
positions where V14 and Rust Gestalt already broadly agree retain the exact V14 target, while large
teacher disagreements receive a bounded correction toward Rust.  The cap prevents one tactical or
out-of-distribution leaf from dragging pruning-calibrated V14 scores by hundreds of centipawns.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import chess
import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--engine-dir", type=Path, required=True)
    ap.add_argument("--gain", type=float, default=0.10)
    ap.add_argument("--threshold-cp", type=int, default=200)
    ap.add_argument("--cap-cp", type=int, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    if not (0.0 <= a.gain <= 1.0):
        raise SystemExit("--gain must lie in [0,1]")
    if a.threshold_cp < 0 or a.cap_cp <= 0:
        raise SystemExit("invalid threshold/cap")

    sys.path.insert(0, str(a.engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state

    rows: list[dict[str, object]] = []
    hard = 0
    shifts: list[int] = []
    disagreements: list[int] = []
    for line in a.teacher.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("teacher_mate") is not None:
            rows.append(r)
            continue
        b = chess.Board(r["fen"])
        e = encode_position(b)
        state = np.empty(EVAL_WIDTH, dtype=np.int32)
        _build_eval_state_into(e.board, state)
        v14 = int(_evaluate_state(e.side, state))
        gestalt = int(r["teacher_cp"])
        error = gestalt - v14
        shift = 0
        if abs(error) >= a.threshold_cp:
            hard += 1
            raw = int(round(a.gain * error))
            shift = max(-a.cap_cp, min(a.cap_cp, raw))
        target = v14 + shift
        nr = dict(r)
        nr["gestalt_cp"] = gestalt
        nr["v14_cp"] = v14
        nr["teacher_cp"] = target
        nr["hardleaf_error_cp"] = error
        nr["hardleaf_shift_cp"] = shift
        nr["hardleaf_gain"] = a.gain
        nr["hardleaf_threshold_cp"] = a.threshold_cp
        nr["hardleaf_cap_cp"] = a.cap_cp
        rows.append(nr)
        shifts.append(abs(shift))
        disagreements.append(abs(error))

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in rows) + "\n")
    nz = [x for x in shifts if x]
    summary = {
        "records": len(rows),
        "hard_records": hard,
        "hard_fraction": hard / max(1, len(shifts)),
        "gain": a.gain,
        "threshold_cp": a.threshold_cp,
        "cap_cp": a.cap_cp,
        "mean_abs_teacher_disagreement_cp": sum(disagreements) / max(1, len(disagreements)),
        "mean_abs_shift_all_cp": sum(shifts) / max(1, len(shifts)),
        "mean_abs_shift_hard_cp": sum(nz) / max(1, len(nz)),
        "max_abs_shift_cp": max(shifts) if shifts else 0,
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
