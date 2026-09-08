#!/usr/bin/env python3
"""Label V14 self-play positions with a fixed-node Stockfish teacher and grouped splits."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

import chess
import chess.engine

MATE_CP = 100_000


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=Path, required=True)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=15_000)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=64)
    parser.add_argument("--split-salt", default="Chess/v14-python-single-residual-a")
    parser.add_argument("--validation-permille", type=int, default=100)
    parser.add_argument("--holdout-permille", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def split_for(group: str, salt: str, validation: int, holdout: int) -> str:
    if validation < 0 or holdout < 0 or validation + holdout >= 1000:
        raise ValueError("invalid split permille values")
    bucket = int.from_bytes(hashlib.sha256((salt + "\0" + group).encode()).digest()[:8], "big") % 1000
    if bucket < holdout:
        return "holdout"
    if bucket < holdout + validation:
        return "validation"
    return "train"


def main() -> int:
    args = parse_args()
    if args.nodes <= 0 or args.threads <= 0 or args.hash_mb <= 0:
        raise SystemExit("teacher resource settings must be positive")
    source = json.loads(args.positions.read_text())
    records = source.get("records", [])
    if not records:
        raise SystemExit("position corpus contains no records")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    split_counts: Counter[str] = Counter()
    group_splits: dict[str, str] = {}
    engine = chess.engine.SimpleEngine.popen_uci(str(args.stockfish.resolve()))
    try:
        engine.configure({"Threads": args.threads, "Hash": args.hash_mb})
        engine_id = dict(engine.id)
        with args.output.open("w", encoding="utf-8") as out:
            for index, record in enumerate(records):
                board = chess.Board(str(record["fen"]))
                info = engine.analyse(board, chess.engine.Limit(nodes=args.nodes), info=chess.engine.INFO_ALL)
                raw_score = info.get("score")
                if raw_score is None:
                    raise RuntimeError(f"Stockfish returned no score at record {index}")
                relative = raw_score.pov(board.turn)
                cp = relative.score(mate_score=MATE_CP)
                if cp is None:
                    raise RuntimeError(f"could not normalise teacher score at record {index}")
                group = str(record["group"])
                split = split_for(group, args.split_salt, args.validation_permille, args.holdout_permille)
                previous = group_splits.setdefault(group, split)
                if previous != split:
                    raise AssertionError("one opening group escaped into multiple splits")
                pv = info.get("pv", [])
                labelled = {
                    "schema_version": 1,
                    "group": group,
                    "game_index": int(record["game_index"]),
                    "ply": int(record["ply"]),
                    "fen": board.fen(),
                    "split": split,
                    "teacher_cp": int(cp),
                    "teacher_mate": relative.mate(),
                    "teacher_best_move": pv[0].uci() if pv else None,
                    "teacher_depth": info.get("depth"),
                    "teacher_seldepth": info.get("seldepth"),
                    "teacher_nodes": info.get("nodes"),
                    "teacher_nps": info.get("nps"),
                }
                out.write(json.dumps(labelled, sort_keys=True) + "\n")
                split_counts[split] += 1
                if (index + 1) % 100 == 0:
                    print("labelled", index + 1, "of", len(records), flush=True)
    finally:
        engine.quit()

    manifest = {
        "schema_version": 1,
        "source_positions": str(args.positions),
        "positions": len(records),
        "groups": len(group_splits),
        "split_counts": dict(sorted(split_counts.items())),
        "split_salt": args.split_salt,
        "validation_permille": args.validation_permille,
        "holdout_permille": args.holdout_permille,
        "teacher": {
            "path": str(args.stockfish.resolve()),
            "id": engine_id,
            "nodes": args.nodes,
            "threads": args.threads,
            "hash_mb": args.hash_mb,
        },
    }
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    if split_counts["train"] == 0 or split_counts["validation"] == 0 or split_counts["holdout"] == 0:
        raise SystemExit(f"all three grouped splits are required: {dict(split_counts)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
