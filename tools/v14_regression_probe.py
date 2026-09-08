#!/usr/bin/env python3
"""Probe named V14 regression fixtures across fixed-node budgets.

This is diagnostic, not an Elo substitute. It records when a candidate first reaches the
Stockfish-preferred move on known historical failures, while also showing whether a control loses a
previously-good fixture. The harness intentionally uses the engine's direct fixed-node search entry
rather than `agent.get_move` so results are deterministic and clock-independent.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, TextIO

import chess


class SearchWorker:
    def __init__(self, engine_dir: Path) -> None:
        self.engine_dir = engine_dir.resolve()
        self.proc = subprocess.Popen(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                "--engine",
                str(self.engine_dir),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.stdin: TextIO = self.proc.stdin
        self.stdout: TextIO = self.proc.stdout

    def search(self, fen: str, nodes: int) -> dict[str, Any]:
        self.stdin.write(json.dumps({"fen": fen, "nodes": nodes}) + "\n")
        self.stdin.flush()
        line = self.stdout.readline()
        if not line:
            raise RuntimeError(f"search worker exited with {self.proc.poll()}")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=5)


def worker_main(engine_dir: Path) -> int:
    # The script itself lives in the repository, so executing it places repo/tools ahead of
    # PYTHONPATH. Insert the reconstructed candidate explicitly before importing experiments.*.
    sys.path.insert(0, str(engine_dir.resolve()))

    import numpy as np
    from experiments.numba_core import encode_position, move_to_uci
    from experiments.numba_search import iterative_search_stateful

    for line in sys.stdin:
        query = json.loads(line)
        board = chess.Board(query["fen"])
        encoded = encode_position(board)
        history = np.empty(0, dtype=np.uint64)
        out = iterative_search_stateful(
            encoded.board,
            encoded.side,
            encoded.castling,
            encoded.ep_square,
            board.halfmove_clock,
            history,
            0,
            int(query["nodes"]),
        )
        print(
            json.dumps(
                {
                    "uci": move_to_uci(int(out[0])),
                    "score": int(out[1]),
                    "depth": int(out[2]),
                    "nodes": int(out[3]),
                }
            ),
            flush=True,
        )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--budgets", default="1000,3000,10000,30000,100000")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def first_hit(rows: list[dict[str, Any]], expected: set[str]) -> int | None:
    for row in rows:
        if row["uci"] in expected:
            return int(row["budget"])
    return None


def run_engine(
    worker: SearchWorker,
    fixtures: list[dict[str, Any]],
    budgets: list[int],
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if fixtures:
        worker.search(fixtures[0]["fen"], min(300, budgets[0]))
    for fixture in fixtures:
        expected = set(fixture["expected_uci"])
        rows = []
        board = chess.Board(fixture["fen"])
        for budget in budgets:
            reply = worker.search(fixture["fen"], budget)
            move = chess.Move.from_uci(reply["uci"])
            if move not in board.legal_moves:
                raise RuntimeError(f"illegal move {move} on fixture {fixture['id']}")
            row = {"budget": budget, **reply, "hit": reply["uci"] in expected}
            rows.append(row)
        result[fixture["id"]] = {
            "category": fixture["category"],
            "expected_uci": sorted(expected),
            "first_hit_nodes": first_hit(rows, expected),
            "searches": rows,
        }
    return result


def main() -> int:
    args = parse_args()
    if args.worker:
        if args.engine is None:
            raise SystemExit("--worker requires --engine")
        return worker_main(args.engine)
    if args.engine is None or args.manifest is None:
        raise SystemExit("--engine and --manifest are required")
    budgets = [int(value) for value in args.budgets.split(",") if value.strip()]
    if not budgets or budgets != sorted(set(budgets)) or budgets[0] <= 0:
        raise SystemExit("--budgets must be unique positive ascending integers")
    manifest = json.loads(args.manifest.read_text())
    fixtures = manifest["fixtures"]
    candidate = SearchWorker(args.engine)
    control = SearchWorker(args.control) if args.control is not None else None
    try:
        candidate_result = run_engine(candidate, fixtures, budgets)
        control_result = run_engine(control, fixtures, budgets) if control is not None else None
    finally:
        candidate.close()
        if control is not None:
            control.close()

    comparisons: dict[str, Any] = {}
    if control_result is not None:
        for fixture in fixtures:
            fixture_id = fixture["id"]
            cand_hit = candidate_result[fixture_id]["first_hit_nodes"]
            ctrl_hit = control_result[fixture_id]["first_hit_nodes"]
            comparisons[fixture_id] = {
                "candidate_first_hit_nodes": cand_hit,
                "control_first_hit_nodes": ctrl_hit,
                "candidate_improves": cand_hit is not None and (ctrl_hit is None or cand_hit < ctrl_hit),
                "candidate_regresses": ctrl_hit is not None and (cand_hit is None or cand_hit > ctrl_hit),
            }

    output = {
        "schema_version": 1,
        "manifest": str(args.manifest),
        "budgets": budgets,
        "candidate": candidate_result,
        "control": control_result,
        "comparisons": comparisons,
    }
    text = json.dumps(output, indent=2, sort_keys=True) + "\n"
    print(text, end="")
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
