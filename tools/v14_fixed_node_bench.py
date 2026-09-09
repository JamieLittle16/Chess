#!/usr/bin/env python3
"""Alternating fixed-node throughput bench for two packaged Python engines."""
from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

import chess

from v14_fixed_node_arena import Worker


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("candidate", type=Path)
    p.add_argument("control", type=Path)
    p.add_argument("--openings", type=Path, required=True)
    p.add_argument("--nodes", type=int, default=25_000)
    p.add_argument("--roots", type=int, default=16)
    p.add_argument("--reps", type=int, default=5)
    p.add_argument("--output", type=Path)
    a = p.parse_args()

    fens = [x.strip() for x in a.openings.read_text().splitlines() if x.strip() and not x.startswith("#")]
    fens = fens[: a.roots]
    if len(fens) != a.roots:
        raise SystemExit("insufficient benchmark roots")
    for fen in fens:
        chess.Board(fen)

    arena = Path(__file__).with_name("v14_fixed_node_arena.py").resolve()
    workers = {
        "candidate": Worker(arena, a.candidate.resolve()),
        "control": Worker(arena, a.control.resolve()),
    }
    samples: dict[str, list[float]] = {"candidate": [], "control": []}
    try:
        for name in ("candidate", "control"):
            workers[name].search(chess.Board(fens[0]), [], min(500, a.nodes))
        for rep in range(a.reps):
            for root_index, fen in enumerate(fens):
                order = ("candidate", "control") if (rep + root_index) % 2 == 0 else ("control", "candidate")
                board = chess.Board(fen)
                for name in order:
                    start = time.perf_counter()
                    result = workers[name].search(board, [], a.nodes)
                    elapsed = time.perf_counter() - start
                    samples[name].append(float(result["nodes"]) / elapsed)
    finally:
        for worker in workers.values():
            worker.close()

    c = statistics.median(samples["candidate"])
    b = statistics.median(samples["control"])
    ratios = [x / y for x, y in zip(samples["candidate"], samples["control"], strict=True)]
    out = {
        "nodes": a.nodes,
        "roots": a.roots,
        "reps": a.reps,
        "candidate_median_nps": c,
        "control_median_nps": b,
        "median_nps_ratio": c / b,
        "median_paired_ratio": statistics.median(ratios),
        "samples_per_engine": len(samples["candidate"]),
    }
    print("FINAL " + json.dumps(out, sort_keys=True), flush=True)
    if a.output:
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
