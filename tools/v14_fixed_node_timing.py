#!/usr/bin/env python3
"""Paired wall-clock timing for packaged Python engines at identical fixed-node searches.

Each engine lives in one persistent subprocess so Numba compilation is paid only during explicit
warmup. Timed rounds alternate which engine runs first to reduce shared-runner drift. Every measured
search is checked for an identical node budget; move/score identity is reported separately rather
than assumed, allowing this harness to qualify performance without hiding semantic divergence.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import TextIO

import chess


def worker_main(engine_dir: Path) -> int:
    sys.path.insert(0, str(engine_dir))
    import numpy as np
    from experiments.numba_core import encode_position, move_to_uci
    from experiments.numba_search import iterative_search_stateful, position_key

    def key_for_fen(fen: str) -> int:
        board = chess.Board(fen)
        encoded = encode_position(board)
        return int(position_key(encoded.board, encoded.side, encoded.castling, encoded.ep_square))

    for line in sys.stdin:
        query = json.loads(line)
        board = chess.Board(query["fen"])
        encoded = encode_position(board)
        prior = query.get("prior", [])
        keep = min(board.halfmove_clock, len(prior))
        history = (
            np.asarray([key_for_fen(fen) for fen in prior[-keep:]], dtype=np.uint64)
            if keep
            else np.empty(0, dtype=np.uint64)
        )
        result = iterative_search_stateful(
            encoded.board,
            encoded.side,
            encoded.castling,
            encoded.ep_square,
            board.halfmove_clock,
            history,
            len(history),
            int(query["nodes"]),
        )
        print(
            json.dumps(
                {
                    "uci": move_to_uci(int(result[0])),
                    "score": int(result[1]),
                    "depth": int(result[2]),
                    "nodes": int(result[3]),
                }
            ),
            flush=True,
        )
    return 0


class Worker:
    def __init__(self, script: Path, engine_dir: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(script), "--worker", str(engine_dir)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.stdin: TextIO = self.proc.stdin
        self.stdout: TextIO = self.proc.stdout

    def search(self, fen: str, nodes: int) -> dict[str, object]:
        self.stdin.write(json.dumps({"fen": fen, "prior": [], "nodes": nodes}) + "\n")
        self.stdin.flush()
        line = self.stdout.readline()
        if not line:
            raise RuntimeError(f"engine worker exited with {self.proc.poll()}")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=5)


def load_fens(path: Path, count: int) -> list[str]:
    rows = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if len(rows) < count:
        raise ValueError(f"requested {count} positions, file has {len(rows)}")
    chosen = rows[:count]
    for fen in chosen:
        chess.Board(fen)
    return chosen


def run_batch(worker: Worker, fens: list[str], nodes: int) -> tuple[float, list[dict[str, object]]]:
    start = time.perf_counter()
    results = [worker.search(fen, nodes) for fen in fens]
    elapsed = time.perf_counter() - start
    for result in results:
        if int(result["nodes"]) < nodes:
            # Iterative search may complete slightly above the budget but must never terminate below
            # the requested node ceiling in an ordinary nonterminal opening root.
            raise RuntimeError(f"short fixed-node search: {result}")
    return elapsed, results


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path, nargs="?")
    parser.add_argument("control", type=Path, nargs="?")
    parser.add_argument("--positions", type=Path)
    parser.add_argument("--count", type=int, default=24)
    parser.add_argument("--nodes", type=int, default=8_000)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.worker is not None:
        return worker_main(args.worker.resolve())
    if args.candidate is None or args.control is None or args.positions is None:
        raise SystemExit("candidate, control and --positions are required")
    if args.count <= 0 or args.nodes <= 0 or args.rounds < 3:
        raise ValueError("count/nodes must be positive and rounds must be >= 3")

    script = Path(__file__).resolve()
    fens = load_fens(args.positions, args.count)
    candidate = Worker(script, args.candidate.resolve())
    control = Worker(script, args.control.resolve())
    candidate_times: list[float] = []
    control_times: list[float] = []
    semantic_checks = 0
    semantic_mismatches = 0
    try:
        # Explicit Numba warmup plus one representative full-budget root outside timed samples.
        for worker in (candidate, control):
            worker.search(fens[0], min(300, args.nodes))
            worker.search(fens[0], args.nodes)

        for round_index in range(args.rounds):
            order = ((candidate, "candidate"), (control, "control"))
            if round_index % 2:
                order = tuple(reversed(order))
            round_results: dict[str, list[dict[str, object]]] = {}
            for worker, label in order:
                elapsed, results = run_batch(worker, fens, args.nodes)
                (candidate_times if label == "candidate" else control_times).append(elapsed)
                round_results[label] = results
            for cand, base in zip(round_results["candidate"], round_results["control"], strict=True):
                semantic_checks += 1
                if (cand["uci"], cand["score"], cand["depth"], cand["nodes"]) != (
                    base["uci"], base["score"], base["depth"], base["nodes"]
                ):
                    semantic_mismatches += 1
            print(
                json.dumps(
                    {
                        "round": round_index + 1,
                        "candidate_seconds": candidate_times[-1],
                        "control_seconds": control_times[-1],
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
    finally:
        candidate.close()
        control.close()

    cand_median = statistics.median(candidate_times)
    control_median = statistics.median(control_times)
    ratio = cand_median / control_median
    summary = {
        "positions_per_round": len(fens),
        "nodes_per_search": args.nodes,
        "rounds": args.rounds,
        "candidate_seconds": candidate_times,
        "control_seconds": control_times,
        "candidate_median_seconds": cand_median,
        "control_median_seconds": control_median,
        "candidate_over_control": ratio,
        "speedup_x": control_median / cand_median,
        "percent_faster": (control_median / cand_median - 1.0) * 100.0,
        "semantic_checks": semantic_checks,
        "semantic_mismatches": semantic_mismatches,
    }
    print("FINAL " + json.dumps(summary, sort_keys=True))
    if args.json_out is not None:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
