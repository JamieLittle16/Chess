#!/usr/bin/env python3
"""Blend exact Gestalt labels toward packaged V14 before compact-student training.

The full Gestalt-distilled H16 is dramatically more accurate statically but destabilises V14 search.
This helper builds an interpolated teacher

    blended = V14 + lambda * (Gestalt - V14)

so the replacement H16 can inject Rust evaluator knowledge while retaining the score distribution
that V14's pruning/qsearch thresholds were tuned around.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import chess
import numpy as np


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--engine-dir", type=Path, required=True)
    ap.add_argument("--blend", type=float, required=True)
    ap.add_argument("--output", type=Path, required=True)
    a = ap.parse_args()
    if not (0.0 <= a.blend <= 1.0):
        raise SystemExit("--blend must lie in [0,1]")

    sys.path.insert(0, str(a.engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state

    rows = []
    abs_shift = []
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
        blended = int(round(v14 + a.blend * (gestalt - v14)))
        nr = dict(r)
        nr["gestalt_cp"] = gestalt
        nr["v14_cp"] = v14
        nr["teacher_cp"] = blended
        nr["blend"] = a.blend
        rows.append(nr)
        abs_shift.append(abs(blended - v14))

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text("\n".join(json.dumps(x, separators=(",", ":")) for x in rows) + "\n")
    print(json.dumps({
        "records": len(rows),
        "blend": a.blend,
        "mean_abs_shift_from_v14_cp": (sum(abs_shift) / len(abs_shift) if abs_shift else 0.0),
        "max_abs_shift_from_v14_cp": (max(abs_shift) if abs_shift else 0),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
