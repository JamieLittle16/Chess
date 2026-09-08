#!/usr/bin/env python3
"""Generate deterministic exact-V13 self-play positions for V14 residual training.

The engine is driven through the same fixed-node, repetition-history-aware worker used by the V14
paired arena. Positions are grouped by their immutable opening root so downstream train/validation/
holdout assignment can never leak one trajectory across splits.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import chess

from v14_fixed_node_arena import Worker


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--nodes", type=int, default=6_000)
    parser.add_argument("--games", type=int, default=80)
    parser.add_argument("--opening-offset", type=int, default=0)
    parser.add_argument("--min-ply", type=int, default=8)
    parser.add_argument("--max-ply", type=int, default=160)
    parser.add_argument("--stride", type=int, default=4)
    parser.add_argument("--max-positions", type=int, default=2_400)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def root_group(board: chess.Board) -> str:
    return "root:" + " ".join(board.fen(en_passant="fen").split()[:4])


def load_openings(path: Path, offset: int, count: int) -> list[str]:
    rows = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    selected = rows[offset : offset + count]
    if len(selected) != count:
        raise SystemExit(f"requested {count} opening roots from offset {offset}; only {len(selected)} available")
    for fen in selected:
        chess.Board(fen)
    return selected


def main() -> int:
    args = parse_args()
    if args.nodes <= 0 or args.games <= 0 or args.stride <= 0 or args.max_positions <= 0:
        raise SystemExit("nodes, games, stride and max-positions must be positive")
    if args.min_ply < 0 or args.max_ply < args.min_ply:
        raise SystemExit("invalid ply window")

    openings = load_openings(args.openings, args.opening_offset, args.games)
    arena_script = Path(__file__).with_name("v14_fixed_node_arena.py").resolve()
    worker = Worker(arena_script, args.engine.resolve())
    records: list[dict[str, object]] = []
    seen_fens: set[str] = set()
    game_summaries: list[dict[str, object]] = []

    try:
        worker.search(chess.Board(openings[0]), [], min(300, args.nodes))
        for game_index, fen in enumerate(openings, start=args.opening_offset):
            board = chess.Board(fen)
            group = root_group(board)
            prior: list[str] = []
            retained = 0
            start_count = len(records)
            while board.ply() <= args.max_ply and len(records) < args.max_positions:
                outcome = board.outcome(claim_draw=True)
                if outcome is not None:
                    break
                ply = board.ply()
                if ply >= args.min_ply and (ply - args.min_ply) % args.stride == 0:
                    position_fen = board.fen()
                    if position_fen not in seen_fens:
                        seen_fens.add(position_fen)
                        records.append(
                            {
                                "schema_version": 1,
                                "group": group,
                                "game_index": game_index,
                                "ply": ply,
                                "fen": position_fen,
                            }
                        )
                        retained += 1
                        if len(records) >= args.max_positions:
                            break
                reply = worker.search(board, prior, args.nodes)
                prior.append(board.fen())
                board.push(reply["move"])

            outcome = board.outcome(claim_draw=True)
            game_summaries.append(
                {
                    "game_index": game_index,
                    "root": fen,
                    "group": group,
                    "retained": retained,
                    "plies_reached": board.ply(),
                    "result": board.result(claim_draw=True) if outcome is not None else "truncated",
                    "records_start": start_count,
                    "records_end": len(records),
                }
            )
            print(json.dumps(game_summaries[-1], sort_keys=True), flush=True)
            if len(records) >= args.max_positions:
                break
    finally:
        worker.close()

    groups = len({str(record["group"]) for record in records})
    payload = {
        "schema_version": 1,
        "engine": str(args.engine.resolve()),
        "opening_file": str(args.openings),
        "nodes_per_move": args.nodes,
        "opening_offset": args.opening_offset,
        "games_requested": args.games,
        "games_played": len(game_summaries),
        "min_ply": args.min_ply,
        "max_ply": args.max_ply,
        "stride": args.stride,
        "positions": len(records),
        "groups": groups,
        "records": records,
        "games": game_summaries,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print("FINAL " + json.dumps({k: v for k, v in payload.items() if k not in {"records", "games"}}, sort_keys=True))
    if len(records) < min(500, args.max_positions):
        raise SystemExit(f"self-play corpus unexpectedly small: {len(records)} positions")
    if groups < min(20, args.games):
        raise SystemExit(f"self-play corpus has too few independent opening groups: {groups}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
