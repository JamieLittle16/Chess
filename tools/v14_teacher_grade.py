#!/usr/bin/env python3
"""Grade V14 regression choices with a pinned full-strength Stockfish teacher.

For each fixture the tool evaluates the unrestricted teacher best line and then evaluates the
candidate and exact-control root moves under identical root-restricted node budgets.  Absolute loss
from the teacher remains useful diagnostic context, while the *direct candidate-minus-control* cp
and WDL expectation deltas are the primary regression metric because they are symmetric and do not
depend on the unrestricted root search distributing its nodes identically.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import chess
import chess.engine

MATE_CP = 100_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--search-budget", type=int, required=True)
    parser.add_argument("--teacher-nodes", type=int, default=300_000)
    parser.add_argument("--hash-mb", type=int, default=64)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser.parse_args()


def score_payload(score: chess.engine.PovScore, pov: chess.Color, ply: int) -> dict[str, Any]:
    relative = score.pov(pov)
    cp = relative.score(mate_score=MATE_CP)
    if cp is None:
        raise RuntimeError("teacher score lacked cp/mate representation")
    wdl = relative.wdl(model="sf", ply=ply)
    return {
        "cp": int(cp),
        "mate": relative.mate(),
        "expectation": float(wdl.expectation()),
        "wins": int(wdl.wins),
        "draws": int(wdl.draws),
        "losses": int(wdl.losses),
    }


def analyse(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    *,
    nodes: int,
    root_move: chess.Move | None = None,
) -> dict[str, Any]:
    engine.configure({"Clear Hash": None})
    info = engine.analyse(
        board,
        chess.engine.Limit(nodes=nodes),
        root_moves=None if root_move is None else [root_move],
        info=chess.engine.INFO_ALL,
    )
    if isinstance(info, list):
        if not info:
            raise RuntimeError("teacher returned empty multipv result")
        info = info[0]
    score = info.get("score")
    if score is None:
        raise RuntimeError("teacher returned no score")
    pv = [move.uci() for move in info.get("pv", [])]
    return {
        "score": score_payload(score, board.turn, board.ply()),
        "best_move": pv[0] if pv else None,
        "pv": pv,
        "depth": info.get("depth"),
        "seldepth": info.get("seldepth"),
        "nodes": info.get("nodes"),
        "nps": info.get("nps"),
    }


def move_at_budget(engine_result: dict[str, Any], budget: int) -> str:
    for row in engine_result["searches"]:
        if int(row["budget"]) == budget:
            return str(row["uci"])
    raise KeyError(f"probe has no search at budget {budget}")


def absolute_loss(best: dict[str, Any], restricted: dict[str, Any]) -> dict[str, float | int]:
    best_cp = int(best["score"]["cp"])
    restricted_cp = int(restricted["score"]["cp"])
    return {
        "cp": max(0, best_cp - restricted_cp),
        "expectation": max(
            0.0,
            float(best["score"]["expectation"])
            - float(restricted["score"]["expectation"]),
        ),
    }


def direct_delta(candidate: dict[str, Any], control: dict[str, Any]) -> dict[str, float | int]:
    """Positive values mean the candidate move is better than the control move."""
    return {
        "cp": int(candidate["score"]["cp"]) - int(control["score"]["cp"]),
        "expectation": float(candidate["score"]["expectation"])
        - float(control["score"]["expectation"]),
    }


def main() -> int:
    args = parse_args()
    if args.teacher_nodes <= 0 or args.search_budget <= 0:
        raise SystemExit("node budgets must be positive")
    probe = json.loads(args.probe.read_text())
    manifest = json.loads(args.manifest.read_text())
    fixtures = {fixture["id"]: fixture for fixture in manifest["fixtures"]}
    if probe.get("control") is None:
        raise SystemExit("probe must contain both candidate and control results")

    stockfish = args.stockfish.resolve()
    engine = chess.engine.SimpleEngine.popen_uci(str(stockfish))
    teacher_id: dict[str, Any] = {}
    try:
        engine.configure({"Threads": 1, "Hash": args.hash_mb, "UCI_LimitStrength": False})
        teacher_id = dict(engine.id)
        rows: list[dict[str, Any]] = []
        for fixture_id, fixture in fixtures.items():
            board = chess.Board(fixture["fen"])
            candidate_uci = move_at_budget(probe["candidate"][fixture_id], args.search_budget)
            control_uci = move_at_budget(probe["control"][fixture_id], args.search_budget)
            candidate_move = chess.Move.from_uci(candidate_uci)
            control_move = chess.Move.from_uci(control_uci)
            if candidate_move not in board.legal_moves or control_move not in board.legal_moves:
                raise RuntimeError(f"illegal probed move on {fixture_id}")

            best = analyse(engine, board, nodes=args.teacher_nodes)
            candidate = analyse(engine, board, nodes=args.teacher_nodes, root_move=candidate_move)
            control = candidate if control_move == candidate_move else analyse(
                engine, board, nodes=args.teacher_nodes, root_move=control_move
            )
            candidate_loss = absolute_loss(best, candidate)
            control_loss = absolute_loss(best, control)
            versus_control = direct_delta(candidate, control)
            row = {
                "id": fixture_id,
                "category": fixture.get("category", "unclassified"),
                "candidate_move": candidate_uci,
                "control_move": control_uci,
                "teacher_best_move": best["best_move"],
                "reported_expected_uci": fixture.get("expected_uci", []),
                "teacher_best_matches_reported": best["best_move"]
                in set(fixture.get("expected_uci", [])),
                "best": best,
                "candidate": candidate,
                "control": control,
                "candidate_loss": candidate_loss,
                "control_loss": control_loss,
                "delta_cp_loss": int(candidate_loss["cp"]) - int(control_loss["cp"]),
                "delta_expectation_loss": float(candidate_loss["expectation"])
                - float(control_loss["expectation"]),
                "candidate_minus_control": versus_control,
            }
            rows.append(row)
            print(
                fixture_id,
                "candidate", candidate_uci,
                "control", control_uci,
                "teacher", best["best_move"],
                "candidate_minus_control_cp", versus_control["cp"],
                flush=True,
            )
    finally:
        engine.quit()

    categories: dict[str, dict[str, float | int]] = {}
    for row in rows:
        category = str(row["category"])
        bucket = categories.setdefault(
            category,
            {
                "positions": 0,
                "candidate_cp_loss": 0,
                "control_cp_loss": 0,
                "delta_cp_loss": 0,
                "candidate_minus_control_cp": 0,
                "candidate_minus_control_expectation": 0.0,
            },
        )
        bucket["positions"] = int(bucket["positions"]) + 1
        bucket["candidate_cp_loss"] = int(bucket["candidate_cp_loss"]) + int(row["candidate_loss"]["cp"])
        bucket["control_cp_loss"] = int(bucket["control_cp_loss"]) + int(row["control_loss"]["cp"])
        bucket["delta_cp_loss"] = int(bucket["delta_cp_loss"]) + int(row["delta_cp_loss"])
        bucket["candidate_minus_control_cp"] = int(bucket["candidate_minus_control_cp"]) + int(
            row["candidate_minus_control"]["cp"]
        )
        bucket["candidate_minus_control_expectation"] = float(
            bucket["candidate_minus_control_expectation"]
        ) + float(row["candidate_minus_control"]["expectation"])

    output = {
        "schema_version": 2,
        "search_budget": args.search_budget,
        "teacher_nodes": args.teacher_nodes,
        "teacher": {
            "path": str(stockfish),
            "sha256": sha256_file(stockfish),
            "id": teacher_id,
            "threads": 1,
            "hash_mb": args.hash_mb,
            "python_chess_version": importlib.metadata.version("chess"),
        },
        "positions": rows,
        "categories": categories,
        "total_delta_cp_loss": sum(int(row["delta_cp_loss"]) for row in rows),
        "total_delta_expectation_loss": sum(float(row["delta_expectation_loss"]) for row in rows),
        "total_candidate_minus_control_cp": sum(
            int(row["candidate_minus_control"]["cp"]) for row in rows
        ),
        "total_candidate_minus_control_expectation": sum(
            float(row["candidate_minus_control"]["expectation"]) for row in rows
        ),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
