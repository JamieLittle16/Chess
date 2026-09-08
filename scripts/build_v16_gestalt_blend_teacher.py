#!/usr/bin/env python3
"""Blend exact Gestalt labels toward packaged V14 before exact-shape H64 training.

Target:
    blended = V14 + lambda * (Gestalt - V14)

The purpose is to inject only a small amount of Rust evaluator knowledge while retaining the score
scale that the Python search was tuned around.
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
    args = ap.parse_args()
    if not 0.0 <= args.blend <= 1.0:
        raise SystemExit("--blend must lie in [0,1]")

    sys.path.insert(0, str(args.engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state

    rows: list[dict[str, object]] = []
    abs_shift: list[int] = []
    for line in args.teacher.read_text().splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        if record.get("teacher_mate") is not None:
            rows.append(record)
            continue
        board = chess.Board(record["fen"])
        encoded = encode_position(board)
        state = np.empty(EVAL_WIDTH, dtype=np.int32)
        _build_eval_state_into(encoded.board, state)
        v14 = int(_evaluate_state(encoded.side, state))
        gestalt = int(record["teacher_cp"])
        blended = int(round(v14 + args.blend * (gestalt - v14)))
        row = dict(record)
        row["gestalt_cp"] = gestalt
        row["v14_cp"] = v14
        row["teacher_cp"] = blended
        row["blend"] = args.blend
        rows.append(row)
        abs_shift.append(abs(blended - v14))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("\n".join(json.dumps(row, separators=(",", ":")) for row in rows) + "\n")
    print(json.dumps({
        "records": len(rows),
        "blend": args.blend,
        "mean_abs_shift_from_v14_cp": sum(abs_shift) / len(abs_shift) if abs_shift else 0.0,
        "max_abs_shift_from_v14_cp": max(abs_shift) if abs_shift else 0,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
