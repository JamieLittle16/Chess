#!/usr/bin/env python3
"""Compare completed depth and CPU wall time on identical fixed-node root searches."""
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
    from experiments.numba_search import iterative_search_stateful

    for line in sys.stdin:
        q = json.loads(line)
        board = chess.Board(q["fen"])
        e = encode_position(board)
        history = np.empty(0, dtype=np.uint64)
        start = time.perf_counter()
        out = iterative_search_stateful(
            e.board, e.side, e.castling, e.ep_square, board.halfmove_clock,
            history, 0, int(q["nodes"]),
        )
        elapsed = time.perf_counter() - start
        print(json.dumps({
            "uci": move_to_uci(int(out[0])), "score": int(out[1]),
            "depth": int(out[2]), "nodes": int(out[3]), "seconds": elapsed,
        }), flush=True)
    return 0


class Worker:
    def __init__(self, script: Path, engine_dir: Path) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, str(script), "--worker", str(engine_dir)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.stdin: TextIO = self.proc.stdin
        self.stdout: TextIO = self.proc.stdout

    def search(self, fen: str, nodes: int) -> dict[str, object]:
        self.stdin.write(json.dumps({"fen": fen, "nodes": nodes}) + "\n")
        self.stdin.flush()
        line = self.stdout.readline()
        if not line:
            raise RuntimeError(f"worker exited with {self.proc.poll()}")
        return json.loads(line)

    def close(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
        self.proc.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("candidate", type=Path, nargs="?")
    p.add_argument("control", type=Path, nargs="?")
    p.add_argument("--positions", type=Path)
    p.add_argument("--count", type=int, default=32)
    p.add_argument("--nodes", type=int, default=20_000)
    p.add_argument("--json-out", type=Path)
    p.add_argument("--worker", type=Path, help=argparse.SUPPRESS)
    return p.parse_args()


def main() -> int:
    a = parse_args()
    if a.worker is not None:
        return worker_main(a.worker.resolve())
    if a.candidate is None or a.control is None or a.positions is None:
        raise SystemExit("candidate, control and --positions required")
    rows = [x.strip() for x in a.positions.read_text().splitlines() if x.strip() and not x.startswith('#')]
    fens = rows[:a.count]
    if len(fens) != a.count:
        raise ValueError("insufficient positions")
    for fen in fens:
        chess.Board(fen)

    script = Path(__file__).resolve()
    cand = Worker(script, a.candidate.resolve())
    base = Worker(script, a.control.resolve())
    crows: list[dict[str, object]] = []
    brows: list[dict[str, object]] = []
    try:
        # JIT warmup is outside measurements.
        cand.search(fens[0], 300)
        base.search(fens[0], 300)
        for index, fen in enumerate(fens):
            # Alternate first mover to reduce runner drift.
            if index % 2 == 0:
                cr = cand.search(fen, a.nodes); br = base.search(fen, a.nodes)
            else:
                br = base.search(fen, a.nodes); cr = cand.search(fen, a.nodes)
            crows.append(cr); brows.append(br)
            print(json.dumps({"index": index, "candidate": cr, "control": br}, sort_keys=True), flush=True)
    finally:
        cand.close(); base.close()

    cdepth = [int(r["depth"]) for r in crows]
    bdepth = [int(r["depth"]) for r in brows]
    ctime = [float(r["seconds"]) for r in crows]
    btime = [float(r["seconds"]) for r in brows]
    summary = {
        "positions": len(fens), "nodes_per_search": a.nodes,
        "candidate_mean_depth": statistics.mean(cdepth),
        "control_mean_depth": statistics.mean(bdepth),
        "candidate_depth_wins": sum(c > b for c, b in zip(cdepth, bdepth, strict=True)),
        "control_depth_wins": sum(b > c for c, b in zip(cdepth, bdepth, strict=True)),
        "equal_depth": sum(c == b for c, b in zip(cdepth, bdepth, strict=True)),
        "candidate_median_seconds": statistics.median(ctime),
        "control_median_seconds": statistics.median(btime),
        "candidate_mean_nodes": statistics.mean(int(r["nodes"]) for r in crows),
        "control_mean_nodes": statistics.mean(int(r["nodes"]) for r in brows),
        "same_move": sum(c["uci"] == b["uci"] for c, b in zip(crows, brows, strict=True)),
        "same_score": sum(c["score"] == b["score"] for c, b in zip(crows, brows, strict=True)),
    }
    print("FINAL " + json.dumps(summary, sort_keys=True))
    if a.json_out is not None:
        a.json_out.parent.mkdir(parents=True, exist_ok=True)
        a.json_out.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
