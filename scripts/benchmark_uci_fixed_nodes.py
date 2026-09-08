#!/usr/bin/env python3
"""Time one UCI engine over a deterministic fixed-node position corpus.

The process stays alive for the whole corpus so NNUE loading and process startup are excluded from
the measured search intervals. Each sample starts with `ucinewgame` and `isready`, then times only
from `go nodes N` until `bestmove`. The script prints machine-readable per-sample and summary lines.
"""

from __future__ import annotations

import argparse
import statistics
import subprocess
import time
from pathlib import Path

POSITIONS = (
    "startpos",
    "fen r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "fen 2r2rk1/pp1b1ppp/2n1pn2/q2p4/3P4/P1NBPN2/1P2BPPP/2RQ1RK1 w - - 2 12",
    "fen 4rrk1/1pp2ppp/p1n1b3/8/3P4/P1P1BN2/1P3PPP/2R2RK1 w - - 0 18",
    "fen 8/2p5/3p2k1/1p1Pp3/pP2P3/P4K2/2P5/8 w - - 0 40",
)


def send(proc: subprocess.Popen[str], command: str) -> None:
    assert proc.stdin is not None
    proc.stdin.write(command + "\n")
    proc.stdin.flush()


def read_until(proc: subprocess.Popen[str], prefix: str) -> str:
    assert proc.stdout is not None
    while True:
        line = proc.stdout.readline()
        if line == "":
            raise RuntimeError(f"engine exited before {prefix!r}")
        line = line.rstrip("\r\n")
        if line.startswith(prefix):
            return line


def ready(proc: subprocess.Popen[str]) -> None:
    send(proc, "isready")
    read_until(proc, "readyok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", type=Path)
    parser.add_argument("--nodes", type=int, default=250_000)
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()

    proc = subprocess.Popen(
        [str(args.engine.resolve())],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    try:
        send(proc, "uci")
        read_until(proc, "uciok")
        ready(proc)
        send(proc, "setoption name Hash value 32")
        ready(proc)

        samples_ms: list[float] = []
        for repeat in range(args.repeats):
            for index, position in enumerate(POSITIONS):
                send(proc, "ucinewgame")
                ready(proc)
                send(proc, f"position {position}")
                start = time.perf_counter_ns()
                send(proc, f"go nodes {args.nodes}")
                bestmove = read_until(proc, "bestmove ")
                elapsed_ms = (time.perf_counter_ns() - start) / 1_000_000.0
                samples_ms.append(elapsed_ms)
                print(
                    f"sample repeat={repeat} position={index} nodes={args.nodes} "
                    f"elapsed_ms={elapsed_ms:.3f} {bestmove}",
                    flush=True,
                )

        total_ms = sum(samples_ms)
        median_ms = statistics.median(samples_ms)
        total_nodes = args.nodes * len(samples_ms)
        effective_nps = total_nodes / (total_ms / 1000.0)
        print(
            f"summary samples={len(samples_ms)} total_nodes={total_nodes} "
            f"total_ms={total_ms:.3f} median_ms={median_ms:.3f} "
            f"effective_nps={effective_nps:.1f}",
            flush=True,
        )
        return 0
    finally:
        if proc.poll() is None:
            try:
                send(proc, "quit")
            except BrokenPipeError:
                pass
            proc.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
