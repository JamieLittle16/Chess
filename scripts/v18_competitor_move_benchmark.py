#!/usr/bin/env python3
"""Benchmark a Little Gambit package against moves played by top Chessathon engines.

The benchmark is intentionally offline-only.  It replays a retained PGN corpus, extracts positions
where a named competitor moved, asks the candidate agent for a move from the exact same FEN and
recorded pre-move clock, and uses full-strength Stockfish as a fixed-node teacher.

For every selected position the teacher receives equal-budget analyses for:
  1. an unrestricted best move;
  2. the historical competitor move; and
  3. the candidate move (reused when identical to the historical move).

This makes candidate-vs-history comparisons much more meaningful than simple best-move agreement.
The benchmark data and Stockfish labels are research artifacts and must never be copied into a
competition submission package.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import chess
import chess.pgn

from stockfish_lab import StockfishTeacher, phase_label, sha256_file

INITIAL_CLOCK_SECONDS = 120.0
PHASES = ("opening_or_early_middlegame", "middlegame", "endgame")


@dataclass(frozen=True)
class Position:
    target: str
    game_id: str
    date: str
    round_name: str
    white: str
    black: str
    game_result: str
    fen: str
    historical_uci: str
    historical_san: str
    pre_clock_ms: int
    ply: int
    fullmove: int
    phase: str


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--pgn", type=Path, required=True)
    ap.add_argument("--engine-dir", type=Path, required=True)
    ap.add_argument("--stockfish", type=Path, required=True)
    ap.add_argument("--target", required=True, help="exact White/Black PGN name")
    ap.add_argument("--positions", type=int, default=48, help="maximum phase-balanced positions")
    ap.add_argument("--nodes", type=int, default=200_000, help="Stockfish nodes per root analysis")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--hash-mb", type=int, default=64)
    ap.add_argument("--pairwise-margin-cp", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--output-dir", type=Path, required=True)
    return ap.parse_args()


def stable_key(seed: int, target: str, position: Position) -> bytes:
    text = f"{seed}|{target}|{position.phase}|{position.fen}|{position.game_id}|{position.ply}"
    return hashlib.sha256(text.encode("utf-8")).digest()


def game_id(index: int, game: chess.pgn.Game) -> str:
    return ":".join(
        (
            str(index),
            game.headers.get("Date", "?"),
            game.headers.get("Round", "?"),
            game.headers.get("White", "?"),
            game.headers.get("Black", "?"),
        )
    )


def collect_positions(path: Path, target: str) -> tuple[list[Position], dict[str, Any]]:
    """Collect target moves and deduplicate repeated starting/trajectory positions by FEN.

    If the same target/FEN occurs in multiple retained games, the later corpus occurrence wins.  The
    source corpus itself is ordered chronologically, so repeated curated openings cannot dominate the
    benchmark merely because they appeared in multiple downloads/games.
    """
    latest_by_fen: dict[str, Position] = {}
    games_seen = 0
    target_games = 0
    raw_target_moves = 0
    clock_missing = 0

    with path.open(encoding="utf-8", errors="replace") as handle:
        while True:
            game = chess.pgn.read_game(handle)
            if game is None:
                break
            games_seen += 1
            white = game.headers.get("White", "")
            black = game.headers.get("Black", "")
            if target not in (white, black):
                continue
            target_games += 1
            gid = game_id(games_seen, game)
            board = game.board()
            previous_post_clock = {
                chess.WHITE: INITIAL_CLOCK_SECONDS,
                chess.BLACK: INITIAL_CLOCK_SECONDS,
            }
            for node in game.mainline():
                move = node.move
                mover = board.turn
                pre_clock = previous_post_clock[mover]
                if (mover == chess.WHITE and white == target) or (mover == chess.BLACK and black == target):
                    raw_target_moves += 1
                    pos = Position(
                        target=target,
                        game_id=gid,
                        date=game.headers.get("Date", "?"),
                        round_name=game.headers.get("Round", "?"),
                        white=white,
                        black=black,
                        game_result=game.headers.get("Result", "*"),
                        fen=board.fen(),
                        historical_uci=move.uci(),
                        historical_san=board.san(move),
                        pre_clock_ms=max(1, int(round(pre_clock * 1000.0))),
                        ply=board.ply() + 1,
                        fullmove=board.fullmove_number,
                        phase=phase_label(board),
                    )
                    latest_by_fen[pos.fen] = pos
                post_clock = node.clock()
                if post_clock is not None:
                    previous_post_clock[mover] = float(post_clock)
                else:
                    clock_missing += 1
                board.push(move)

    positions = list(latest_by_fen.values())
    meta = {
        "games_seen": games_seen,
        "target_games": target_games,
        "raw_target_moves": raw_target_moves,
        "unique_target_fens": len(positions),
        "deduplicated_target_moves": raw_target_moves - len(positions),
        "move_nodes_without_clock_comment": clock_missing,
    }
    return positions, meta


def balanced_sample(positions: list[Position], limit: int, seed: int, target: str) -> list[Position]:
    if limit <= 0:
        raise ValueError("--positions must be positive")
    if len(positions) <= limit:
        return sorted(positions, key=lambda p: (p.round_name, p.ply, p.fen))

    buckets: dict[str, list[Position]] = {phase: [] for phase in PHASES}
    for position in positions:
        buckets.setdefault(position.phase, []).append(position)
    for phase in buckets:
        buckets[phase].sort(key=lambda p: stable_key(seed, target, p))

    # Equal phase allocation first. Any unavailable quota is filled from the remaining pool using
    # the same deterministic hash ordering, so selection is reproducible and candidate-blind.
    base = limit // len(PHASES)
    remainder = limit % len(PHASES)
    selected: list[Position] = []
    selected_ids: set[tuple[str, int]] = set()
    for idx, phase in enumerate(PHASES):
        want = base + (1 if idx < remainder else 0)
        for position in buckets.get(phase, [])[:want]:
            selected.append(position)
            selected_ids.add((position.fen, position.ply))

    if len(selected) < limit:
        rest = [p for p in positions if (p.fen, p.ply) not in selected_ids]
        rest.sort(key=lambda p: stable_key(seed ^ 0x5EED, target, p))
        selected.extend(rest[: limit - len(selected)])

    return sorted(
        selected,
        key=lambda p: (
            PHASES.index(p.phase) if p.phase in PHASES else 99,
            stable_key(seed, target, p),
        ),
    )


def reset_agent(agent: Any) -> None:
    """Reset known cross-call state so every static position is an independent strength probe."""
    if hasattr(agent, "_GAME_KEYS"):
        agent._GAME_KEYS.clear()
    for name in ("_PENDING_AFTER_OUR_MOVE", "_LAST_CALL_TIME_LEFT_MS", "_LAST_GET_MOVE_ELAPSED_MS"):
        if hasattr(agent, name):
            setattr(agent, name, None)
    if hasattr(agent, "_CLOCK_OVERHEAD_EMA_MS"):
        agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    if hasattr(agent, "_CLOCK_FEEDBACK_SAMPLES"):
        agent._CLOCK_FEEDBACK_SAMPLES = 0
    zero_arrays = ("_HASH_KEYS", "_TT_TABLE", "_QUIET_HISTORY", "_CONT_HISTORY", "_CONTINUATION_HISTORY")
    for name in zero_arrays:
        array = getattr(agent, name, None)
        if array is not None and hasattr(array, "fill"):
            array.fill(0)
    hash_moves = getattr(agent, "_HASH_MOVES", None)
    if hash_moves is not None and hasattr(hash_moves, "fill"):
        hash_moves.fill(-1)


def load_agent(engine_dir: Path) -> tuple[Any, float]:
    sys.path.insert(0, str(engine_dir.resolve()))
    started = time.perf_counter()
    import agent  # type: ignore[import-not-found]
    init_seconds = time.perf_counter() - started
    return agent, init_seconds


def analyse_move(teacher: StockfishTeacher, board: chess.Board, move: chess.Move) -> Any:
    return teacher.analyse(board, pov=board.turn, root_move=move)


def mean(values: Iterable[float]) -> float:
    items = list(values)
    return statistics.fmean(items) if items else 0.0


def summarize_side(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    losses = [int(row[f"{prefix}_cp_loss"]) for row in rows]
    ex_losses = [float(row[f"{prefix}_expectation_loss"]) for row in rows]
    return {
        "mean_cp_loss": round(mean(losses), 3),
        "median_cp_loss": round(statistics.median(losses), 3) if losses else 0.0,
        "mean_expectation_loss": round(mean(ex_losses), 6),
        "best_move_matches": sum(bool(row[f"{prefix}_matches_sf_best"]) for row in rows),
        "best_move_match_rate": round(
            mean(1.0 if row[f"{prefix}_matches_sf_best"] else 0.0 for row in rows), 6
        ),
        "inaccuracies_cp_ge_30": sum(loss >= 30 for loss in losses),
        "mistakes_cp_ge_80": sum(loss >= 80 for loss in losses),
        "blunders_cp_ge_150": sum(loss >= 150 for loss in losses),
        "severe_cp_ge_300": sum(loss >= 300 for loss in losses),
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_positions, corpus_meta = collect_positions(args.pgn, args.target)
    if not all_positions:
        raise SystemExit(f"target engine {args.target!r} was not found in the PGN corpus")
    positions = balanced_sample(all_positions, args.positions, args.seed, args.target)
    phase_counts = Counter(position.phase for position in positions)

    agent, init_seconds = load_agent(args.engine_dir)
    rows: list[dict[str, Any]] = []
    illegal_moves = 0

    with StockfishTeacher(
        args.stockfish,
        nodes=args.nodes,
        threads=args.threads,
        hash_mb=args.hash_mb,
    ) as teacher:
        teacher_manifest = teacher.manifest()
        for index, position in enumerate(positions, start=1):
            board = chess.Board(position.fen)
            historical = chess.Move.from_uci(position.historical_uci)
            if historical not in board.legal_moves:
                raise RuntimeError(f"historical illegal move {historical} at {position.fen}")

            reset_agent(agent)
            started = time.perf_counter()
            candidate_uci = str(agent.get_move(position.fen, position.pre_clock_ms)).strip()
            candidate_elapsed_s = time.perf_counter() - started
            try:
                candidate = chess.Move.from_uci(candidate_uci)
            except ValueError:
                candidate = chess.Move.null()
            candidate_legal = candidate in board.legal_moves
            if not candidate_legal:
                illegal_moves += 1

            best = teacher.analyse(board, pov=board.turn)
            historical_eval = analyse_move(teacher, board, historical)
            if candidate_legal and candidate == historical:
                candidate_eval = historical_eval
            elif candidate_legal:
                candidate_eval = analyse_move(teacher, board, candidate)
            else:
                candidate_eval = None

            best_cp = int(best.score.cp)
            hist_cp = int(historical_eval.score.cp)
            hist_loss = max(0, best_cp - hist_cp)
            best_expectation = float(best.score.expectation)
            hist_expectation = float(historical_eval.score.expectation)
            hist_ex_loss = max(0.0, best_expectation - hist_expectation)

            if candidate_eval is None:
                cand_cp = -100_000
                cand_expectation = 0.0
                cand_loss = 100_000
                cand_ex_loss = max(0.0, best_expectation)
                candidate_matches_best = False
                pair_delta_cp = -100_000
            else:
                cand_cp = int(candidate_eval.score.cp)
                cand_expectation = float(candidate_eval.score.expectation)
                cand_loss = max(0, best_cp - cand_cp)
                cand_ex_loss = max(0.0, best_expectation - cand_expectation)
                candidate_matches_best = candidate_uci == best.best_move
                pair_delta_cp = cand_cp - hist_cp

            if pair_delta_cp > args.pairwise_margin_cp:
                pairwise = "win"
                pair_points = 1.0
            elif pair_delta_cp < -args.pairwise_margin_cp:
                pairwise = "loss"
                pair_points = 0.0
            else:
                pairwise = "tie"
                pair_points = 0.5

            row = {
                "index": index,
                "target": args.target,
                "game_id": position.game_id,
                "date": position.date,
                "round": position.round_name,
                "white": position.white,
                "black": position.black,
                "game_result": position.game_result,
                "ply": position.ply,
                "fullmove": position.fullmove,
                "phase": position.phase,
                "fen": position.fen,
                "pre_clock_ms": position.pre_clock_ms,
                "historical_uci": position.historical_uci,
                "historical_san": position.historical_san,
                "candidate_uci": candidate_uci,
                "candidate_legal": candidate_legal,
                "candidate_elapsed_s": round(candidate_elapsed_s, 6),
                "sf_best_uci": best.best_move,
                "sf_best_cp": best_cp,
                "sf_best_expectation": round(best_expectation, 6),
                "historical_cp": hist_cp,
                "historical_expectation": round(hist_expectation, 6),
                "historical_cp_loss": hist_loss,
                "historical_expectation_loss": round(hist_ex_loss, 6),
                "historical_matches_sf_best": position.historical_uci == best.best_move,
                "candidate_cp": cand_cp,
                "candidate_expectation": round(cand_expectation, 6),
                "candidate_cp_loss": cand_loss,
                "candidate_expectation_loss": round(cand_ex_loss, 6),
                "candidate_matches_sf_best": candidate_matches_best,
                "candidate_minus_historical_cp": pair_delta_cp,
                "candidate_minus_historical_expectation": round(cand_expectation - hist_expectation, 6),
                "pairwise": pairwise,
                "pairwise_points": pair_points,
                "sf_best_depth": best.depth,
                "sf_historical_depth": historical_eval.depth,
                "sf_candidate_depth": None if candidate_eval is None else candidate_eval.depth,
            }
            rows.append(row)
            print(
                f"{args.target}: {index}/{len(positions)} {position.phase} "
                f"hist={position.historical_uci} cand={candidate_uci} sf={best.best_move} "
                f"delta={pair_delta_cp:+d}cp {pairwise}",
                flush=True,
            )

    historical_summary = summarize_side(rows, "historical")
    candidate_summary = summarize_side(rows, "candidate")
    pair_counts = Counter(row["pairwise"] for row in rows)
    pair_score = mean(float(row["pairwise_points"]) for row in rows)
    net_cp_gain = sum(int(row["historical_cp_loss"]) - int(row["candidate_cp_loss"]) for row in rows)
    net_expectation_gain = sum(
        float(row["historical_expectation_loss"]) - float(row["candidate_expectation_loss"])
        for row in rows
    )
    better_80 = sum(int(row["candidate_minus_historical_cp"]) >= 80 for row in rows)
    worse_80 = sum(int(row["candidate_minus_historical_cp"]) <= -80 for row in rows)

    gate_checks = {
        "zero_illegal_moves": illegal_moves == 0,
        "mean_cp_loss_not_worse": candidate_summary["mean_cp_loss"] <= historical_summary["mean_cp_loss"],
        "mean_expectation_loss_not_worse": (
            candidate_summary["mean_expectation_loss"] <= historical_summary["mean_expectation_loss"]
        ),
        "pairwise_score_at_least_half": pair_score >= 0.5,
        "mistakes_ge_80_not_more_frequent": (
            candidate_summary["mistakes_cp_ge_80"] <= historical_summary["mistakes_cp_ge_80"]
        ),
        "large_regressions_not_more_than_large_gains": worse_80 <= better_80,
    }
    summary = {
        "schema_version": 1,
        "target": args.target,
        "positions": len(rows),
        "phase_counts": dict(sorted(phase_counts.items())),
        "corpus": corpus_meta,
        "candidate": candidate_summary,
        "historical": historical_summary,
        "pairwise": {
            "margin_cp": args.pairwise_margin_cp,
            "wins": pair_counts.get("win", 0),
            "ties": pair_counts.get("tie", 0),
            "losses": pair_counts.get("loss", 0),
            "score": round(pair_score, 6),
            "net_cp_loss_reduction": net_cp_gain,
            "mean_cp_loss_reduction": round(net_cp_gain / len(rows), 3) if rows else 0.0,
            "net_expectation_loss_reduction": round(net_expectation_gain, 6),
            "large_gains_ge_80_cp": better_80,
            "large_regressions_ge_80_cp": worse_80,
        },
        "gate_checks": gate_checks,
        "gate_pass": all(gate_checks.values()),
        "candidate_runtime": {
            "import_seconds": round(init_seconds, 6),
            "mean_move_seconds": round(mean(float(row["candidate_elapsed_s"]) for row in rows), 6),
            "max_move_seconds": round(max(float(row["candidate_elapsed_s"]) for row in rows), 6) if rows else 0.0,
            "illegal_moves": illegal_moves,
        },
        "teacher": teacher_manifest,
        "selection": {
            "limit": args.positions,
            "seed": args.seed,
            "phase_balanced": True,
            "position_identity": "target + FEN (latest corpus occurrence retained)",
        },
        "inputs": {
            "pgn": str(args.pgn.resolve()),
            "pgn_sha256": sha256_file(args.pgn),
            "engine_dir": str(args.engine_dir.resolve()),
            "stockfish": str(args.stockfish.resolve()),
        },
    }

    write_csv(args.output_dir / "positions.csv", rows)
    with (args.output_dir / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    return 0 if illegal_moves == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
