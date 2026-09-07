#!/usr/bin/env python3
"""Mine objective move losses from retained engine PGNs with full-strength Stockfish.

Each analysed engine move receives two equal fixed-node teacher searches: an unrestricted search for
Stockfish's preferred move and a root-restricted search of the move actually played. This makes the
reported loss far more useful than comparing against a shallow one-line annotation and avoids using
Stockfish's deliberately weakened UCI_LimitStrength mode for diagnostics.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import chess
import chess.pgn

from stockfish_lab import (
    StockfishTeacher,
    loss_bucket,
    move_kind,
    phase_label,
    sha256_file,
    write_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pgn", type=Path, required=True, help="retained match PGN")
    parser.add_argument("--stockfish", type=Path, required=True, help="full-strength Stockfish UCI binary")
    parser.add_argument("--engine-name", required=True, help="exact White/Black PGN header name to analyse")
    parser.add_argument("--nodes", type=int, default=100_000, help="teacher nodes per unrestricted/restricted search")
    parser.add_argument("--threads", type=int, default=1)
    parser.add_argument("--hash-mb", type=int, default=32)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--min-ply", type=int, default=1, help="first one-based game ply to analyse")
    parser.add_argument("--max-ply", type=int, default=10_000, help="last one-based game ply to analyse")
    parser.add_argument("--max-positions", type=int, default=None, help="optional global analysis cap")
    return parser.parse_args()


def flatten_row(
    *,
    game_index: int,
    game_id: str,
    board: chess.Board,
    move: chess.Move,
    san: str,
    clock_seconds: float | None,
    engine_color: chess.Color,
    best: Any,
    played: Any,
) -> dict[str, Any]:
    best_cp = best.score.cp
    played_cp = played.score.cp
    cp_loss = max(0, best_cp - played_cp)
    expectation_loss = max(0.0, best.score.expectation - played.score.expectation)

    best_move = chess.Move.from_uci(best.best_move) if best.best_move is not None else None
    played_kind = move_kind(board, move)
    best_kind = move_kind(board, best_move) if best_move is not None else "none"
    best_forcing = best_kind in {"capture", "promotion", "capture_promotion", "quiet_check"}
    played_forcing = played_kind in {"capture", "promotion", "capture_promotion", "quiet_check"}

    return {
        "game_index": game_index,
        "game_id": game_id,
        "ply": board.ply() + 1,
        "fullmove": board.fullmove_number,
        "engine_color": "white" if engine_color == chess.WHITE else "black",
        "fen_before": board.fen(),
        "played_uci": move.uci(),
        "played_san": san,
        "played_kind": played_kind,
        "played_gives_check": board.gives_check(move),
        "best_uci": best.best_move,
        "best_kind": best_kind,
        "best_is_forcing": best_forcing,
        "played_is_forcing": played_forcing,
        "phase": phase_label(board),
        "clock_seconds": clock_seconds,
        "best_cp": best_cp,
        "played_cp": played_cp,
        "cp_loss": cp_loss,
        "loss_bucket": loss_bucket(cp_loss),
        "best_expectation": round(best.score.expectation, 6),
        "played_expectation": round(played.score.expectation, 6),
        "expectation_loss": round(expectation_loss, 6),
        "best_mate": best.score.mate,
        "played_mate": played.score.mate,
        "teacher_depth_best": best.depth,
        "teacher_depth_played": played.depth,
        "teacher_seldepth_best": best.seldepth,
        "teacher_seldepth_played": played.seldepth,
        "teacher_nodes_best": best.nodes,
        "teacher_nodes_played": played.nodes,
        "teacher_nps_best": best.nps,
        "teacher_nps_played": played.nps,
        "best_pv": " ".join(best.pv),
        "played_pv": " ".join(played.pv),
    }


def game_identifier(game_index: int, game: chess.pgn.Game) -> str:
    white = game.headers.get("White", "?")
    black = game.headers.get("Black", "?")
    event = game.headers.get("Event", "?")
    round_name = game.headers.get("Round", "?")
    return f"{game_index}:{event}:{round_name}:{white}:{black}"


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    rows: list[dict[str, Any]] = []
    game_count = 0
    target_game_count = 0

    with StockfishTeacher(
        args.stockfish,
        nodes=args.nodes,
        threads=args.threads,
        hash_mb=args.hash_mb,
    ) as teacher:
        teacher_manifest = teacher.manifest()
        with args.pgn.open(encoding="utf-8", errors="replace") as pgn_handle:
            while True:
                game = chess.pgn.read_game(pgn_handle)
                if game is None:
                    break
                game_count += 1
                white = game.headers.get("White", "")
                black = game.headers.get("Black", "")
                target_colors = {
                    color
                    for color, name in ((chess.WHITE, white), (chess.BLACK, black))
                    if name == args.engine_name
                }
                if not target_colors:
                    continue
                target_game_count += 1

                board = game.board()
                game_id = game_identifier(game_count, game)
                for node in game.mainline():
                    move = node.move
                    one_based_ply = board.ply() + 1
                    analyse = (
                        board.turn in target_colors
                        and args.min_ply <= one_based_ply <= args.max_ply
                    )
                    if analyse:
                        san = board.san(move)
                        best = teacher.analyse(board, pov=board.turn)
                        played = teacher.analyse(board, pov=board.turn, root_move=move)
                        rows.append(
                            flatten_row(
                                game_index=game_count,
                                game_id=game_id,
                                board=board,
                                move=move,
                                san=san,
                                clock_seconds=node.clock(),
                                engine_color=board.turn,
                                best=best,
                                played=played,
                            )
                        )
                        if args.max_positions is not None and len(rows) >= args.max_positions:
                            break
                    board.push(move)
                if args.max_positions is not None and len(rows) >= args.max_positions:
                    break

    jsonl_path = args.output_dir / "positions.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    csv_path = args.output_dir / "positions.csv"
    if rows:
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    else:
        csv_path.write_text("")

    by_bucket = Counter(row["loss_bucket"] for row in rows)
    by_phase = Counter(row["phase"] for row in rows)
    by_played_kind = Counter(row["played_kind"] for row in rows)
    by_best_kind = Counter(row["best_kind"] for row in rows)
    large_losses = [row for row in rows if row["cp_loss"] >= 80]
    quiet_large_losses = [
        row for row in large_losses if row["played_kind"] == "quiet" and not row["best_is_forcing"]
    ]
    summary = {
        "games_seen": game_count,
        "games_with_target_engine": target_game_count,
        "positions_analysed": len(rows),
        "mean_cp_loss": round(sum(row["cp_loss"] for row in rows) / len(rows), 3) if rows else 0.0,
        "mean_expectation_loss": round(
            sum(row["expectation_loss"] for row in rows) / len(rows), 6
        )
        if rows
        else 0.0,
        "large_losses_cp_ge_80": len(large_losses),
        "quiet_nonforcing_large_losses": len(quiet_large_losses),
        "by_loss_bucket": dict(sorted(by_bucket.items())),
        "by_phase": dict(sorted(by_phase.items())),
        "by_played_kind": dict(sorted(by_played_kind.items())),
        "by_best_kind": dict(sorted(by_best_kind.items())),
    }
    write_json(args.output_dir / "summary.json", summary)

    manifest = {
        "schema_version": 1,
        "input_pgn": str(args.pgn.resolve()),
        "input_pgn_sha256": sha256_file(args.pgn),
        "target_engine_name": args.engine_name,
        "min_ply": args.min_ply,
        "max_ply": args.max_ply,
        "max_positions": args.max_positions,
        "teacher": teacher_manifest,
        "outputs": {
            "jsonl": jsonl_path.name,
            "csv": csv_path.name,
            "summary": "summary.json",
        },
    }
    write_json(args.output_dir / "manifest.json", manifest)

    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
