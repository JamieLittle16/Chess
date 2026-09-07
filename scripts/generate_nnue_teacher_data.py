#!/usr/bin/env python3
"""Generate reproducible Stockfish teacher records for learned-evaluation experiments.

PGN positions are split by whole source game, never by individual position, so adjacent positions from
the same game cannot leak across train/validation/holdout. EPD/FEN sources use one source line as the
group unless the caller prepares a stronger external grouping scheme.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Iterator

import chess
import chess.pgn

from stockfish_lab import StockfishTeacher, sha256_file, write_json


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--pgn", type=Path, action="append", default=[])
    parser.add_argument("--epd", type=Path, action="append", default=[])
    parser.add_argument("--nodes", type=int, default=100_000)
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=32)
    parser.add_argument("--stride", type=int, default=1, help="retain every Nth eligible position")
    parser.add_argument("--min-ply", type=int, default=1)
    parser.add_argument("--max-ply", type=int, default=10_000)
    parser.add_argument("--max-positions", type=int, default=None)
    parser.add_argument("--validation-permille", type=int, default=100)
    parser.add_argument("--holdout-permille", type=int, default=100)
    parser.add_argument("--split-salt", default="Chess/m5-nnue-teacher-v1")
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def deterministic_split(group: str, *, salt: str, validation: int, holdout: int) -> str:
    if validation < 0 or holdout < 0 or validation + holdout >= 1000:
        raise ValueError("validation + holdout permille must be in [0, 999]")
    digest = hashlib.sha256((salt + "\0" + group).encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 1000
    if bucket < holdout:
        return "holdout"
    if bucket < holdout + validation:
        return "validation"
    return "train"


def pgn_positions(path: Path, min_ply: int, max_ply: int) -> Iterator[tuple[str, str, chess.Board]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        game_index = 0
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                return
            game_index += 1
            group = f"pgn:{path.resolve()}:{game_index}"
            board = game.board()
            # Include the game root as ply zero only when explicitly requested.
            if min_ply <= 0 <= max_ply:
                yield group, "root", board.copy(stack=False)
            for node in game.mainline():
                board.push(node.move)
                ply = board.ply()
                if min_ply <= ply <= max_ply:
                    yield group, f"ply:{ply}", board.copy(stack=False)


def epd_positions(path: Path) -> Iterator[tuple[str, str, chess.Board]]:
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            # The first four EPD fields are exactly the board/turn/castling/en-passant FEN prefix.
            fields = stripped.split()
            if len(fields) < 4:
                raise ValueError(f"{path}:{line_no}: expected at least four EPD/FEN fields")
            fen = " ".join(fields[:4]) + " 0 1"
            board = chess.Board(fen)
            group = f"epd:{path.resolve()}:{line_no}"
            yield group, f"line:{line_no}", board


def main() -> int:
    args = parse_args()
    if not args.pgn and not args.epd:
        raise SystemExit("at least one --pgn or --epd source is required")
    if args.stride <= 0:
        raise SystemExit("--stride must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    sources = [
        {"kind": "pgn", "path": str(path.resolve()), "sha256": sha256_file(path)}
        for path in args.pgn
    ] + [
        {"kind": "epd", "path": str(path.resolve()), "sha256": sha256_file(path)}
        for path in args.epd
    ]

    position_stream: Iterator[tuple[str, str, chess.Board]]
    def all_positions() -> Iterator[tuple[str, str, chess.Board]]:
        for path in args.pgn:
            yield from pgn_positions(path, args.min_ply, args.max_ply)
        for path in args.epd:
            yield from epd_positions(path)

    output_path = args.output_dir / "teacher.jsonl"
    split_counts: Counter[str] = Counter()
    seen = 0
    written = 0

    with StockfishTeacher(
        args.stockfish,
        nodes=args.nodes,
        threads=args.threads,
        hash_mb=args.hash_mb,
    ) as teacher, output_path.open("w", encoding="utf-8") as output:
        teacher_manifest = teacher.manifest()
        for group, source_position, board in all_positions():
            if seen % args.stride != 0:
                seen += 1
                continue
            seen += 1

            analysis = teacher.analyse(board, pov=board.turn)
            split = deterministic_split(
                group,
                salt=args.split_salt,
                validation=args.validation_permille,
                holdout=args.holdout_permille,
            )
            record = {
                "schema_version": 1,
                "group": group,
                "source_position": source_position,
                "split": split,
                "fen": board.fen(),
                "side_to_move": "white" if board.turn == chess.WHITE else "black",
                "ply": board.ply(),
                "teacher_cp": analysis.score.cp,
                "teacher_mate": analysis.score.mate,
                "teacher_expectation": round(analysis.score.expectation, 6),
                "teacher_wins": analysis.score.wins,
                "teacher_draws": analysis.score.draws,
                "teacher_losses": analysis.score.losses,
                "teacher_best_move": analysis.best_move,
                "teacher_depth": analysis.depth,
                "teacher_seldepth": analysis.seldepth,
                "teacher_nodes": analysis.nodes,
                "teacher_nps": analysis.nps,
                "teacher_pv": list(analysis.pv),
            }
            output.write(json.dumps(record, sort_keys=True) + "\n")
            split_counts[split] += 1
            written += 1
            if args.max_positions is not None and written >= args.max_positions:
                break

    manifest = {
        "schema_version": 1,
        "sources": sources,
        "teacher": teacher_manifest,
        "selection": {
            "stride": args.stride,
            "min_ply": args.min_ply,
            "max_ply": args.max_ply,
            "max_positions": args.max_positions,
        },
        "split": {
            "salt": args.split_salt,
            "validation_permille": args.validation_permille,
            "holdout_permille": args.holdout_permille,
            "assignment_unit": "whole PGN game; individual EPD line",
        },
        "positions_seen_before_stride": seen,
        "positions_written": written,
        "split_counts": dict(sorted(split_counts.items())),
        "output": output_path.name,
    }
    write_json(args.output_dir / "manifest.json", manifest)
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
