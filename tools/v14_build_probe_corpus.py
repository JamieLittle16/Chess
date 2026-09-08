#!/usr/bin/env python3
"""Build a deterministic unlabeled V14 regression corpus from diverse legal rollouts.

The corpus is not a puzzle suite and carries no hand-authored best moves.  It exists to compare a
candidate and the exact V13 control on the *same* broad positions, after which pinned Stockfish grades
their chosen moves.  Positions are stratified with cheap observable tags so aggregate gains cannot
hide a concentrated regression in low-material, advanced-pawn, king-pressure or quiet positions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import random
from typing import Iterable

import chess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=48)
    parser.add_argument("--seed", type=int, default=2026090802)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser.parse_args()


def load_openings(path: Path) -> list[str]:
    rows = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    if not rows:
        raise SystemExit("opening file is empty")
    for fen in rows:
        chess.Board(fen)
    return rows


def has_advanced_passed_pawn(board: chess.Board) -> bool:
    for color in (chess.WHITE, chess.BLACK):
        enemy_pawns = board.pieces(chess.PAWN, not color)
        for square in board.pieces(chess.PAWN, color):
            rank = chess.square_rank(square)
            relative_rank = rank if color == chess.WHITE else 7 - rank
            if relative_rank < 5:
                continue
            file = chess.square_file(square)
            passed = True
            for enemy in enemy_pawns:
                enemy_file = chess.square_file(enemy)
                if abs(enemy_file - file) > 1:
                    continue
                enemy_rank = chess.square_rank(enemy)
                if (color == chess.WHITE and enemy_rank > rank) or (color == chess.BLACK and enemy_rank < rank):
                    passed = False
                    break
            if passed:
                return True
    return False


def classify(board: chess.Board) -> str:
    piece_count = len(board.piece_map())
    nonpawn_nonking = sum(
        len(board.pieces(piece, color))
        for color in (chess.WHITE, chess.BLACK)
        for piece in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )
    legal = list(board.legal_moves)
    captures = sum(board.is_capture(move) for move in legal)
    checks = sum(board.gives_check(move) for move in legal)

    if piece_count <= 8 or nonpawn_nonking <= 2:
        return "low_material"
    if has_advanced_passed_pawn(board):
        return "advanced_passed_pawn"
    if checks >= 1:
        return "king_pressure"
    if captures >= 4:
        return "forcing_rich"
    if captures == 0:
        return "quiet"
    return "general"


def canonical_position_key(board: chess.Board) -> str:
    # Fullmove number is irrelevant to search semantics; preserve halfmove clock because rule 50 is
    # not irrelevant. Castling and EP state remain part of the key.
    fields = board.fen().split()
    return " ".join(fields[:5])


def shuffled_indices(length: int, rng: random.Random) -> Iterable[int]:
    indices = list(range(length))
    rng.shuffle(indices)
    return indices


def main() -> int:
    args = parse_args()
    if args.positions <= 0:
        raise SystemExit("--positions must be positive")
    openings = load_openings(args.openings)
    rng = random.Random(args.seed)
    rollout_choices = (0, 4, 8, 12, 20, 32, 48, 64)
    fixtures: list[dict[str, object]] = []
    seen: set[str] = set()
    attempts = 0

    while len(fixtures) < args.positions and attempts < args.positions * 50:
        attempts += 1
        opening_index = list(shuffled_indices(len(openings), rng))[0]
        board = chess.Board(openings[opening_index])
        requested_plies = rollout_choices[rng.randrange(len(rollout_choices))]
        played = 0
        for _ in range(requested_plies):
            if board.is_game_over(claim_draw=False):
                break
            legal = list(board.legal_moves)
            if not legal:
                break
            board.push(legal[rng.randrange(len(legal))])
            played += 1
        if board.is_game_over(claim_draw=False):
            continue
        key = canonical_position_key(board)
        if key in seen:
            continue
        seen.add(key)
        category = classify(board)
        fixtures.append({
            "id": f"broad-{len(fixtures):03d}",
            "category": category,
            "fen": board.fen(),
            "source_opening_index": opening_index,
            "random_rollout_plies": played,
        })

    if len(fixtures) != args.positions:
        raise SystemExit(f"only generated {len(fixtures)} unique non-terminal positions")
    counts: dict[str, int] = {}
    for fixture in fixtures:
        category = str(fixture["category"])
        counts[category] = counts.get(category, 0) + 1

    opening_digest = hashlib.sha256(args.openings.read_bytes()).hexdigest()
    output = {
        "schema_version": 1,
        "kind": "deterministic_unlabeled_teacher_graded_probe_corpus",
        "seed": args.seed,
        "opening_file": str(args.openings),
        "opening_sha256": opening_digest,
        "positions": args.positions,
        "category_counts": dict(sorted(counts.items())),
        "fixtures": fixtures,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v for k, v in output.items() if k != "fixtures"}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
