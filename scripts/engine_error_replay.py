#!/usr/bin/env python3
"""Replay Stockfish-mined Little Gambit errors at increasing engine node budgets.

The input is ``positions.jsonl`` from ``stockfish_error_mining.py``.  We select the
largest objective losses, ask the candidate engine for a move at several independent
fixed-node budgets, then score every selected move with one fixed-budget full-strength
Stockfish teacher.  This distinguishes mistakes that disappear with more search from
mistakes that remain persistent at the largest tested budget.

A persistent error is deliberately *not* labelled an evaluation bug: it may still be a
search/selectivity failure.  The replay narrows the next experiment; it does not replace
root-cause inspection or paired strength testing.
"""
from __future__ import annotations

import argparse
import csv
import importlib.metadata
import json
from collections import Counter
from pathlib import Path
from typing import Any

import chess
import chess.engine

from stockfish_lab import (
    StockfishTeacher,
    loss_bucket,
    move_kind,
    score_record,
    sha256_file,
    write_json,
)

DEFAULT_NODE_BUDGETS = (2_000, 10_000, 50_000, 200_000)


def parse_node_budgets(text: str) -> tuple[int, ...]:
    try:
        budgets = tuple(int(part.strip()) for part in text.split(",") if part.strip())
    except ValueError as error:
        raise argparse.ArgumentTypeError("node budgets must be comma-separated integers") from error
    if not budgets:
        raise argparse.ArgumentTypeError("at least one node budget is required")
    if any(budget <= 0 for budget in budgets):
        raise argparse.ArgumentTypeError("node budgets must be positive")
    if tuple(sorted(set(budgets))) != budgets:
        raise argparse.ArgumentTypeError("node budgets must be unique and strictly increasing")
    return budgets


def classify_depth_response(losses: list[int]) -> str:
    """Classify only the observed response to additional search effort."""
    if not losses:
        raise ValueError("at least one replay loss is required")
    shallow = losses[0]
    deepest = losses[-1]
    if deepest < 30:
        return "resolved_by_search"
    if deepest <= shallow - 50:
        return "improves_with_search"
    if deepest >= shallow + 50:
        return "worsens_with_search"
    return "persistent_at_tested_budget"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--positions", type=Path, required=True, help="positions.jsonl from stockfish_error_mining")
    parser.add_argument("--engine", type=Path, required=True, help="Little Gambit UCI executable")
    parser.add_argument("--stockfish", type=Path, required=True, help="full-strength Stockfish UCI executable")
    parser.add_argument("--teacher-nodes", type=int, default=100_000)
    parser.add_argument(
        "--node-budgets",
        type=parse_node_budgets,
        default=DEFAULT_NODE_BUDGETS,
        help="strictly increasing comma-separated Little Gambit node budgets",
    )
    parser.add_argument("--engine-hash-mb", type=int, default=32)
    parser.add_argument("--teacher-threads", type=int, default=1)
    parser.add_argument("--teacher-hash-mb", type=int, default=64)
    parser.add_argument("--min-cp-loss", type=int, default=80)
    parser.add_argument("--max-positions", type=int, default=120)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def load_ranked_positions(path: Path, *, min_cp_loss: int, max_positions: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]
    selected = [row for row in rows if int(row["cp_loss"]) >= min_cp_loss]
    selected.sort(
        key=lambda row: (
            -float(row.get("expectation_loss", 0.0)),
            -int(row["cp_loss"]),
            int(row.get("game_index", 0)),
            int(row.get("ply", 0)),
        )
    )
    return selected[:max_positions]


def engine_score_payload(info: dict[str, Any], board: chess.Board) -> dict[str, Any]:
    raw_score = info.get("score")
    if raw_score is None:
        return {"engine_cp": None, "engine_mate": None, "engine_expectation": None}
    record = score_record(raw_score, board.turn, board.ply())
    return {
        "engine_cp": record.cp,
        "engine_mate": record.mate,
        "engine_expectation": round(record.expectation, 6),
    }


def replay_position(
    *,
    engine: chess.engine.SimpleEngine,
    teacher: StockfishTeacher,
    source: dict[str, Any],
    node_budgets: tuple[int, ...],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    board = chess.Board(source["fen_before"])
    teacher_best = teacher.analyse(board, pov=board.turn)
    if teacher_best.best_move is None:
        raise RuntimeError(f"teacher returned no move for nonterminal source position: {board.fen()}")

    restricted_cache: dict[str, Any] = {}
    budget_rows: list[dict[str, Any]] = []
    for budget in node_budgets:
        # A fresh game token forces ucinewgame between budgets.  Each budget therefore receives
        # exactly its own node allowance rather than inheriting a warmed transposition table.
        result = engine.play(
            board,
            chess.engine.Limit(nodes=budget),
            game=object(),
            info=chess.engine.INFO_ALL,
        )
        if result.move is None:
            raise RuntimeError(f"engine returned no move for nonterminal source position: {board.fen()}")
        uci = result.move.uci()
        if uci not in restricted_cache:
            restricted_cache[uci] = teacher.analyse(board, pov=board.turn, root_move=result.move)
        teacher_played = restricted_cache[uci]
        cp_loss = max(0, teacher_best.score.cp - teacher_played.score.cp)
        expectation_loss = max(
            0.0,
            teacher_best.score.expectation - teacher_played.score.expectation,
        )
        row = {
            "node_budget": budget,
            "engine_move": uci,
            "engine_move_kind": move_kind(board, result.move),
            "matches_teacher_best": uci == teacher_best.best_move,
            "teacher_best_move": teacher_best.best_move,
            "teacher_best_cp": teacher_best.score.cp,
            "teacher_move_cp": teacher_played.score.cp,
            "teacher_cp_loss": cp_loss,
            "teacher_loss_bucket": loss_bucket(cp_loss),
            "teacher_best_expectation": round(teacher_best.score.expectation, 6),
            "teacher_move_expectation": round(teacher_played.score.expectation, 6),
            "teacher_expectation_loss": round(expectation_loss, 6),
            "engine_nodes_reported": result.info.get("nodes"),
            "engine_depth_reported": result.info.get("depth"),
            "engine_seldepth_reported": result.info.get("seldepth"),
            **engine_score_payload(result.info, board),
        }
        budget_rows.append(row)

    losses = [int(row["teacher_cp_loss"]) for row in budget_rows]
    summary = {
        "game_index": source.get("game_index"),
        "game_id": source.get("game_id"),
        "ply": source.get("ply"),
        "phase": source.get("phase"),
        "fen_before": source["fen_before"],
        "original_played_uci": source.get("played_uci"),
        "original_best_uci": source.get("best_uci"),
        "original_cp_loss": source.get("cp_loss"),
        "original_expectation_loss": source.get("expectation_loss"),
        "original_played_kind": source.get("played_kind"),
        "original_best_kind": source.get("best_kind"),
        "depth_response": classify_depth_response(losses),
        "shallow_replay_cp_loss": losses[0],
        "deepest_replay_cp_loss": losses[-1],
        "best_replay_cp_loss": min(losses),
        "deepest_engine_move": budget_rows[-1]["engine_move"],
        "deepest_matches_teacher_best": budget_rows[-1]["matches_teacher_best"],
    }
    return summary, budget_rows


def main() -> int:
    args = parse_args()
    if args.teacher_nodes <= 0:
        raise SystemExit("--teacher-nodes must be positive")
    if args.min_cp_loss < 0:
        raise SystemExit("--min-cp-loss must be non-negative")
    if args.max_positions <= 0:
        raise SystemExit("--max-positions must be positive")
    args.output_dir.mkdir(parents=True, exist_ok=False)

    selected = load_ranked_positions(
        args.positions,
        min_cp_loss=args.min_cp_loss,
        max_positions=args.max_positions,
    )

    position_rows: list[dict[str, Any]] = []
    budget_rows: list[dict[str, Any]] = []
    engine_path = args.engine.resolve()

    engine = chess.engine.SimpleEngine.popen_uci(str(engine_path))
    try:
        if "Hash" in engine.options:
            engine.configure({"Hash": args.engine_hash_mb})
        engine_id = dict(engine.id)
        with StockfishTeacher(
            args.stockfish,
            nodes=args.teacher_nodes,
            threads=args.teacher_threads,
            hash_mb=args.teacher_hash_mb,
        ) as teacher:
            teacher_manifest = teacher.manifest()
            for index, source in enumerate(selected, start=1):
                summary, replays = replay_position(
                    engine=engine,
                    teacher=teacher,
                    source=source,
                    node_budgets=args.node_budgets,
                )
                summary["replay_index"] = index
                position_rows.append(summary)
                for replay in replays:
                    budget_rows.append(
                        {
                            "replay_index": index,
                            "game_index": source.get("game_index"),
                            "ply": source.get("ply"),
                            "fen_before": source["fen_before"],
                            **replay,
                        }
                    )
    finally:
        engine.quit()

    with (args.output_dir / "positions.jsonl").open("w", encoding="utf-8") as handle:
        for row in position_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    for filename, rows in (("positions.csv", position_rows), ("budgets.csv", budget_rows)):
        path = args.output_dir / filename
        if rows:
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
        else:
            path.write_text("")

    by_response = Counter(row["depth_response"] for row in position_rows)
    summary_payload = {
        "eligible_positions_selected": len(selected),
        "positions_replayed": len(position_rows),
        "node_budgets": list(args.node_budgets),
        "by_depth_response": dict(sorted(by_response.items())),
        "mean_shallow_cp_loss": round(
            sum(row["shallow_replay_cp_loss"] for row in position_rows) / len(position_rows), 3
        )
        if position_rows
        else 0.0,
        "mean_deepest_cp_loss": round(
            sum(row["deepest_replay_cp_loss"] for row in position_rows) / len(position_rows), 3
        )
        if position_rows
        else 0.0,
        "deepest_teacher_best_match_rate": round(
            sum(bool(row["deepest_matches_teacher_best"]) for row in position_rows)
            / len(position_rows),
            6,
        )
        if position_rows
        else 0.0,
    }
    write_json(args.output_dir / "summary.json", summary_payload)
    manifest = {
        "schema_version": 1,
        "input_positions": str(args.positions.resolve()),
        "input_positions_sha256": sha256_file(args.positions),
        "engine_path": str(engine_path),
        "engine_sha256": sha256_file(engine_path),
        "engine_id": engine_id,
        "engine_hash_mb": args.engine_hash_mb,
        "node_budgets": list(args.node_budgets),
        "min_source_cp_loss": args.min_cp_loss,
        "max_positions": args.max_positions,
        "teacher": teacher_manifest,
        "python_chess_version": importlib.metadata.version("chess"),
        "classification_contract": {
            "resolved_by_search": "deepest replay loss < 30 cp",
            "improves_with_search": "deepest replay improves by at least 50 cp versus shallow",
            "worsens_with_search": "deepest replay worsens by at least 50 cp versus shallow",
            "persistent_at_tested_budget": "none of the above; does not imply evaluation root cause",
        },
    }
    write_json(args.output_dir / "manifest.json", manifest)

    print(json.dumps(summary_payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
