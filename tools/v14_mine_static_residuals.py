#!/usr/bin/env python3
"""Mine diverse hard V13 positions from a labelled self-play teacher corpus.

Only the training split is eligible. Validation remains dedicated to model selection and holdout is
never inspected. Selection ranks by absolute Stockfish-minus-V13 static-evaluation residual, caps
one example per opening root, and records cheap chess categories for later regression reporting.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

import chess
import numpy as np

from v14_build_probe_corpus import classify


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--teacher", type=Path, required=True)
    parser.add_argument("--engine-dir", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=32)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser.parse_args()


def load_v13(engine_dir: Path):
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state
    return encode_position, _build_eval_state_into, _evaluate_state, int(EVAL_WIDTH)


def main() -> int:
    args = parse_args()
    if args.positions <= 0:
        raise SystemExit("--positions must be positive")
    encode_position, build_state, evaluate_state, eval_width = load_v13(args.engine_dir)

    candidates: list[dict[str, Any]] = []
    with args.teacher.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("split") != "train" or record.get("teacher_mate") is not None:
                continue
            board = chess.Board(record["fen"])
            encoded = encode_position(board)
            state = np.empty(eval_width, dtype=np.int32)
            build_state(encoded.board, state)
            v13_cp = int(evaluate_state(encoded.side, state))
            teacher_cp = int(record["teacher_cp"])
            residual_cp = teacher_cp - v13_cp
            candidates.append(
                {
                    "group": str(record["group"]),
                    "fen": board.fen(),
                    "category": classify(board),
                    "teacher_cp": teacher_cp,
                    "v13_static_cp": v13_cp,
                    "static_residual_cp": residual_cp,
                    "abs_static_residual_cp": abs(residual_cp),
                    "source_game_index": int(record["game_index"]),
                    "source_ply": int(record["ply"]),
                    "teacher_best_move": record.get("teacher_best_move"),
                    "teacher_nodes": record.get("teacher_nodes"),
                }
            )

    candidates.sort(
        key=lambda row: (
            int(row["abs_static_residual_cp"]),
            abs(int(row["teacher_cp"])),
            -int(row["source_game_index"]),
        ),
        reverse=True,
    )
    fixtures: list[dict[str, Any]] = []
    used_groups: set[str] = set()
    for row in candidates:
        group = str(row["group"])
        if group in used_groups:
            continue
        used_groups.add(group)
        fixture = dict(row)
        fixture["id"] = f"v14-hard-static-{len(fixtures):03d}"
        fixtures.append(fixture)
        if len(fixtures) == args.positions:
            break

    if len(fixtures) != args.positions:
        raise SystemExit(f"only found {len(fixtures)} independent eligible roots")
    category_counts: dict[str, int] = {}
    for row in fixtures:
        category = str(row["category"])
        category_counts[category] = category_counts.get(category, 0) + 1

    output = {
        "schema_version": 1,
        "kind": "v13_selfplay_train_split_static_residual_hard_corpus",
        "selection": {
            "eligible_split": "train_only",
            "rank": "abs(Stockfish15k_cp - exact_V13_static_cp)",
            "max_positions_per_opening_root": 1,
            "validation_inspected": False,
            "holdout_inspected": False,
        },
        "positions": len(fixtures),
        "candidate_positions_considered": len(candidates),
        "category_counts": dict(sorted(category_counts.items())),
        "min_abs_static_residual_cp": min(int(row["abs_static_residual_cp"]) for row in fixtures),
        "median_abs_static_residual_cp": sorted(int(row["abs_static_residual_cp"]) for row in fixtures)[len(fixtures)//2],
        "max_abs_static_residual_cp": max(int(row["abs_static_residual_cp"]) for row in fixtures),
        "fixtures": fixtures,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "fixtures"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
