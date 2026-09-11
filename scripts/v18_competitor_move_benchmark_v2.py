#!/usr/bin/env python3
"""V2 benchmark of Little Gambit against historical Chessathon opponent decisions.

V2 fixes a subtle V1 oracle issue: an unrestricted fixed-node Stockfish score is not directly
comparable with a separately root-restricted score. We now use the unrestricted search only to
*discover* Stockfish's preferred move, then give that move, the historical move, and the candidate
move equal fixed-node root-restricted searches. CPL/WDL loss is measured from the best score among
those equally searched roots. Therefore candidate-vs-historical CPL gain is exactly their direct
root-score difference, without mixing unlike search budgets.

This is offline research tooling. Do not package the corpus, Stockfish labels, or lookup results into
a competition submission.
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
    ap.add_argument("--target", required=True, help="exact White/Black PGN player name")
    ap.add_argument("--positions", type=int, default=48, help="maximum phase-balanced positions")
    ap.add_argument("--nodes", type=int, default=200_000, help="nodes for every Stockfish query")
    ap.add_argument("--threads", type=int, default=1)
    ap.add_argument("--hash-mb", type=int, default=64)
    ap.add_argument("--pairwise-margin-cp", type=int, default=8)
    ap.add_argument("--seed", type=int, default=20260911)
    ap.add_argument("--output-dir", type=Path, required=True)
    return ap.parse_args()


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


def stable_key(seed: int, target: str, position: Position) -> bytes:
    payload = (
        f"{seed}|{target}|{position.phase}|{position.fen}|"
        f"{position.game_id}|{position.ply}"
    )
    return hashlib.sha256(payload.encode()).digest()


def collect_positions(path: Path, target: str) -> tuple[list[Position], dict[str, Any]]:
    latest_by_fen: dict[str, Position] = {}
    games_seen = target_games = raw_target_moves = clock_missing = 0

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
                is_target = (mover == chess.WHITE and white == target) or (
                    mover == chess.BLACK and black == target
                )
                if is_target:
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
                        pre_clock_ms=max(1, int(round(pre_clock * 1000))),
                        ply=board.ply() + 1,
                        fullmove=board.fullmove_number,
                        phase=phase_label(board),
                    )
                    latest_by_fen[pos.fen] = pos
                post_clock = node.clock()
                if post_clock is None:
                    clock_missing += 1
                else:
                    previous_post_clock[mover] = float(post_clock)
                board.push(move)

    positions = list(latest_by_fen.values())
    return positions, {
        "games_seen": games_seen,
        "target_games": target_games,
        "raw_target_moves": raw_target_moves,
        "unique_target_fens": len(positions),
        "deduplicated_target_moves": raw_target_moves - len(positions),
        "move_nodes_without_clock_comment": clock_missing,
    }


def balanced_sample(
    positions: list[Position], limit: int, seed: int, target: str
) -> list[Position]:
    if limit <= 0:
        raise ValueError("--positions must be positive")
    if len(positions) <= limit:
        return sorted(positions, key=lambda p: (p.round_name, p.ply, p.fen))

    buckets: dict[str, list[Position]] = {phase: [] for phase in PHASES}
    for position in positions:
        buckets.setdefault(position.phase, []).append(position)
    for phase_positions in buckets.values():
        phase_positions.sort(key=lambda p: stable_key(seed, target, p))

    base, extra = divmod(limit, len(PHASES))
    selected: list[Position] = []
    selected_fens: set[str] = set()
    for idx, phase in enumerate(PHASES):
        want = base + (idx < extra)
        for position in buckets.get(phase, [])[:want]:
            selected.append(position)
            selected_fens.add(position.fen)

    if len(selected) < limit:
        rest = [p for p in positions if p.fen not in selected_fens]
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
    """Clear known state so every static position is an independent probe."""
    game_keys = getattr(agent, "_GAME_KEYS", None)
    if game_keys is not None and hasattr(game_keys, "clear"):
        game_keys.clear()
    for name in (
        "_PENDING_AFTER_OUR_MOVE",
        "_LAST_CALL_TIME_LEFT_MS",
        "_LAST_GET_MOVE_ELAPSED_MS",
    ):
        if hasattr(agent, name):
            setattr(agent, name, None)
    if hasattr(agent, "_CLOCK_OVERHEAD_EMA_MS"):
        agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    if hasattr(agent, "_CLOCK_FEEDBACK_SAMPLES"):
        agent._CLOCK_FEEDBACK_SAMPLES = 0
    for name in (
        "_HASH_KEYS",
        "_TT_TABLE",
        "_QUIET_HISTORY",
        "_CONT_HISTORY",
        "_CONTINUATION_HISTORY",
    ):
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

    return agent, time.perf_counter() - started


def mean(values: Iterable[float]) -> float:
    values = list(values)
    return statistics.fmean(values) if values else 0.0


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def summarize_side(rows: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    losses = [int(row[f"{prefix}_cp_loss"]) for row in rows]
    expectation_losses = [float(row[f"{prefix}_expectation_loss"]) for row in rows]
    return {
        "mean_cp_loss": round(mean(losses), 3),
        "median_cp_loss": round(statistics.median(losses), 3) if losses else 0.0,
        "mean_expectation_loss": round(mean(expectation_losses), 6),
        "best_move_matches": sum(bool(row[f"{prefix}_matches_sf_best"]) for row in rows),
        "best_move_match_rate": round(
            mean(1.0 if row[f"{prefix}_matches_sf_best"] else 0.0 for row in rows), 6
        ),
        "inaccuracies_cp_ge_30": sum(loss >= 30 for loss in losses),
        "mistakes_cp_ge_80": sum(loss >= 80 for loss in losses),
        "blunders_cp_ge_150": sum(loss >= 150 for loss in losses),
        "severe_cp_ge_300": sum(loss >= 300 for loss in losses),
    }


def main() -> int:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    all_positions, corpus_meta = collect_positions(args.pgn, args.target)
    if not all_positions:
        raise SystemExit(f"target engine {args.target!r} not found")
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
        for index, position in enumerate(positions, 1):
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

            # The unrestricted call discovers a preferred move only. All comparative scores below
            # come from equal-budget root-restricted calls.
            discovery = teacher.analyse(board, pov=board.turn)
            if discovery.best_move is None:
                raise RuntimeError(f"Stockfish returned no PV at {position.fen}")
            discovered_best = chess.Move.from_uci(discovery.best_move)
            best_root = teacher.analyse(board, pov=board.turn, root_move=discovered_best)

            if historical == discovered_best:
                historical_eval = best_root
            else:
                historical_eval = teacher.analyse(board, pov=board.turn, root_move=historical)

            if not candidate_legal:
                candidate_eval = None
            elif candidate == discovered_best:
                candidate_eval = best_root
            elif candidate == historical:
                candidate_eval = historical_eval
            else:
                candidate_eval = teacher.analyse(board, pov=board.turn, root_move=candidate)

            best_root_cp = int(best_root.score.cp)
            hist_cp = int(historical_eval.score.cp)
            best_root_exp = float(best_root.score.expectation)
            hist_exp = float(historical_eval.score.expectation)
            if candidate_eval is None:
                cand_cp = -100_000
                cand_exp = 0.0
            else:
                cand_cp = int(candidate_eval.score.cp)
                cand_exp = float(candidate_eval.score.expectation)

            # Use one shared reference built only from comparable equal-root searches. If a
            # historical/candidate move scores above the discovery move after its full root search,
            # it becomes the reference rather than being clipped away.
            reference_cp = max(best_root_cp, hist_cp, cand_cp)
            reference_exp = max(best_root_exp, hist_exp, cand_exp)
            hist_loss = reference_cp - hist_cp
            cand_loss = reference_cp - cand_cp
            hist_exp_loss = max(0.0, reference_exp - hist_exp)
            cand_exp_loss = max(0.0, reference_exp - cand_exp)
            pair_delta_cp = cand_cp - hist_cp

            if pair_delta_cp > args.pairwise_margin_cp:
                pairwise, pair_points = "win", 1.0
            elif pair_delta_cp < -args.pairwise_margin_cp:
                pairwise, pair_points = "loss", 0.0
            else:
                pairwise, pair_points = "tie", 0.5

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
                "sf_discovery_best_uci": discovery.best_move,
                "sf_discovery_cp": int(discovery.score.cp),
                "sf_discovery_expectation": round(float(discovery.score.expectation), 6),
                "sf_best_root_cp": best_root_cp,
                "sf_best_root_expectation": round(best_root_exp, 6),
                "reference_cp": reference_cp,
                "reference_expectation": round(reference_exp, 6),
                "historical_cp": hist_cp,
                "historical_expectation": round(hist_exp, 6),
                "historical_cp_loss": hist_loss,
                "historical_expectation_loss": round(hist_exp_loss, 6),
                "historical_matches_sf_best": position.historical_uci == discovery.best_move,
                "candidate_cp": cand_cp,
                "candidate_expectation": round(cand_exp, 6),
                "candidate_cp_loss": cand_loss,
                "candidate_expectation_loss": round(cand_exp_loss, 6),
                "candidate_matches_sf_best": candidate_uci == discovery.best_move,
                "candidate_minus_historical_cp": pair_delta_cp,
                "candidate_minus_historical_expectation": round(cand_exp - hist_exp, 6),
                "pairwise": pairwise,
                "pairwise_points": pair_points,
                "sf_discovery_depth": discovery.depth,
                "sf_best_root_depth": best_root.depth,
                "sf_historical_depth": historical_eval.depth,
                "sf_candidate_depth": None if candidate_eval is None else candidate_eval.depth,
            }
            rows.append(row)
            print(
                f"{args.target}: {index}/{len(positions)} {position.phase} "
                f"hist={position.historical_uci} cand={candidate_uci} "
                f"sf={discovery.best_move} delta={pair_delta_cp:+d}cp {pairwise}",
                flush=True,
            )

    historical_summary = summarize_side(rows, "historical")
    candidate_summary = summarize_side(rows, "candidate")
    pair_counts = Counter(row["pairwise"] for row in rows)
    pair_score = mean(float(row["pairwise_points"]) for row in rows)
    net_cp_gain = sum(
        int(row["historical_cp_loss"]) - int(row["candidate_cp_loss"]) for row in rows
    )
    net_expectation_gain = sum(
        float(row["historical_expectation_loss"]) - float(row["candidate_expectation_loss"])
        for row in rows
    )
    better_80 = sum(int(row["candidate_minus_historical_cp"]) >= 80 for row in rows)
    worse_80 = sum(int(row["candidate_minus_historical_cp"]) <= -80 for row in rows)

    gate_checks = {
        "zero_illegal_moves": illegal_moves == 0,
        "mean_cp_loss_not_worse": candidate_summary["mean_cp_loss"] <= historical_summary["mean_cp_loss"],
        "mean_expectation_loss_not_worse": candidate_summary["mean_expectation_loss"] <= historical_summary["mean_expectation_loss"],
        "pairwise_score_at_least_half": pair_score >= 0.5,
        "mistakes_ge_80_not_more_frequent": candidate_summary["mistakes_cp_ge_80"] <= historical_summary["mistakes_cp_ge_80"],
        "large_regressions_not_more_than_large_gains": worse_80 <= better_80,
    }
    summary = {
        "schema_version": 2,
        "oracle_protocol": "discover unrestricted; score discovered-best/historical/candidate as equal-node restricted roots; use shared max root reference",
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
