#!/usr/bin/env python3
"""Paired wall-clock arena between a packaged Python agent and the Rust UCI engine.

Python/Numba is imported and warmed before any chess clock starts. Both engines then persist for
all games. Actual wall time is charged externally while each engine also receives the live clock
through its native interface (`get_move(fen, time_left_ms)` for Python, UCI clocks for Rust).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import subprocess
import sys
import threading
import time
from collections import Counter
from pathlib import Path

import chess


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python-dir", required=True)
    parser.add_argument("--rust-bin", required=True)
    parser.add_argument("--gestalt", required=True)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--base-ms", type=int, default=2500)
    parser.add_argument("--inc-ms", type=int, default=50)
    parser.add_argument("--max-plies", type=int, default=220)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


class LineProcess:
    def __init__(self, argv: list[str], *, env: dict[str, str] | None = None) -> None:
        self.proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self.proc.stdin is not None and self.proc.stdout is not None
        self.lines: queue.Queue[str | None] = queue.Queue()

        def pump() -> None:
            assert self.proc.stdout is not None
            for line in self.proc.stdout:
                self.lines.put(line.rstrip("\n"))
            self.lines.put(None)

        threading.Thread(target=pump, daemon=True).start()

    def send(self, line: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(line + "\n")
        self.proc.stdin.flush()

    def read(self, timeout: float) -> str:
        line = self.lines.get(timeout=timeout)
        if line is None:
            raise RuntimeError(f"process exited with code {self.proc.poll()}")
        return line

    def wait_for(self, prefix: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"timeout waiting for {prefix!r}")
            line = self.read(remaining)
            if line.startswith(prefix):
                return line

    def stop(self) -> None:
        if self.proc.poll() is None:
            try:
                self.send("quit")
                self.proc.wait(timeout=2)
            except Exception:
                self.proc.kill()
                self.proc.wait()


class PythonAgent:
    def __init__(self, engine_dir: str) -> None:
        self.p = LineProcess([sys.executable, "tools/v14_agent_runner.py", engine_dir])
        msg = json.loads(self.p.read(120.0))
        if not msg.get("ready"):
            raise RuntimeError(f"bad Python runner ready message: {msg}")
        # Force the first compiled search before clocks begin. The returned move is discarded.
        self.move(chess.Board(), 2500, 120.0)
        self.reset()

    def reset(self) -> None:
        self.p.send(json.dumps({"reset": True}))
        msg = json.loads(self.p.read(5.0))
        if not msg.get("reset"):
            raise RuntimeError(f"bad Python reset message: {msg}")

    def move(self, board: chess.Board, own_ms: float, timeout: float) -> tuple[chess.Move, float]:
        start = time.monotonic()
        self.p.send(json.dumps({"fen": board.fen(), "time_left_ms": max(0, int(own_ms))}))
        msg = json.loads(self.p.read(timeout))
        elapsed = (time.monotonic() - start) * 1000.0
        move = chess.Move.from_uci(msg["move"])
        return move, elapsed

    def stop(self) -> None:
        self.p.stop()


class RustEngine:
    def __init__(self, binary: str, gestalt: str) -> None:
        env = os.environ.copy()
        env["CHESS_GESTALT_NETWORK"] = gestalt
        self.p = LineProcess([binary], env=env)
        self.p.send("uci")
        self.p.wait_for("uciok", 10.0)
        self.p.send("setoption name Hash value 32")
        self.p.send("isready")
        self.p.wait_for("readyok", 10.0)
        # Warm search/evaluator before clocks begin.
        self.p.send("position startpos")
        self.p.send("go movetime 100")
        self.p.wait_for("bestmove ", 5.0)
        self.reset()

    def reset(self) -> None:
        self.p.send("ucinewgame")
        self.p.send("isready")
        self.p.wait_for("readyok", 5.0)

    def move(
        self,
        board: chess.Board,
        white_ms: float,
        black_ms: float,
        inc_ms: int,
        timeout: float,
    ) -> tuple[chess.Move, float]:
        self.p.send("position fen " + board.fen())
        self.p.send(
            f"go wtime {max(0, int(white_ms))} btime {max(0, int(black_ms))} "
            f"winc {inc_ms} binc {inc_ms}"
        )
        start = time.monotonic()
        line = self.p.wait_for("bestmove ", timeout)
        elapsed = (time.monotonic() - start) * 1000.0
        move = chess.Move.from_uci(line.split()[1])
        return move, elapsed

    def stop(self) -> None:
        self.p.stop()


def main() -> int:
    args = parse_args()
    roots = [line.strip() for line in args.openings.read_text().splitlines() if line.strip()]
    python = PythonAgent(args.python_dir)
    rust = RustEngine(args.rust_bin, args.gestalt)
    rows: list[dict[str, object]] = []
    try:
        for opening_index, fen in enumerate(roots):
            for python_white in (True, False):
                python.reset()
                rust.reset()
                board = chess.Board(fen)
                clocks = {chess.WHITE: float(args.base_ms), chess.BLACK: float(args.base_ms)}
                python_times: list[float] = []
                rust_times: list[float] = []
                termination = "max-ply-draw"
                score = 0.5
                for _ply in range(args.max_plies):
                    outcome = board.outcome(claim_draw=True)
                    if outcome is not None:
                        score = 0.5 if outcome.winner is None else float(outcome.winner == python_white)
                        termination = board.result(claim_draw=True)
                        break
                    side = board.turn
                    python_to_move = bool(side) == python_white
                    own_ms = clocks[side]
                    timeout = (max(0.0, own_ms) + 1500.0) / 1000.0
                    try:
                        if python_to_move:
                            move, elapsed = python.move(board, own_ms, timeout)
                            python_times.append(elapsed)
                        else:
                            move, elapsed = rust.move(
                                board,
                                clocks[chess.WHITE],
                                clocks[chess.BLACK],
                                args.inc_ms,
                                timeout,
                            )
                            rust_times.append(elapsed)
                    except Exception as exc:
                        score = 0.0 if python_to_move else 1.0
                        termination = f"engine-failure:{type(exc).__name__}"
                        break
                    if move not in board.legal_moves:
                        score = 0.0 if python_to_move else 1.0
                        termination = "illegal-move"
                        break
                    clocks[side] -= elapsed
                    if clocks[side] < 0.0:
                        score = 0.0 if python_to_move else 1.0
                        termination = "flag"
                        break
                    board.push(move)
                    clocks[side] += args.inc_ms

                row = {
                    "opening": opening_index,
                    "python_white": python_white,
                    "score": score,
                    "termination": termination,
                    "python_mean_move_ms": sum(python_times) / len(python_times) if python_times else None,
                    "rust_mean_move_ms": sum(rust_times) / len(rust_times) if rust_times else None,
                }
                rows.append(row)
                print(json.dumps(row), flush=True)
    finally:
        python.stop()
        rust.stop()

    score = sum(float(row["score"]) for row in rows)
    games = len(rows)
    fraction = score / games
    elo = 400.0 * math.log10(fraction / (1.0 - fraction)) if 0.0 < fraction < 1.0 else None
    pair_scores = [float(rows[i]["score"]) + float(rows[i + 1]["score"]) for i in range(0, games, 2)]
    py_means = [float(row["python_mean_move_ms"]) for row in rows if row["python_mean_move_ms"] is not None]
    rust_means = [float(row["rust_mean_move_ms"]) for row in rows if row["rust_mean_move_ms"] is not None]
    result = {
        "candidate": "Python V14 + trusted continuity + stable presort",
        "reference": "Rust V15 + Gestalt v85",
        "games": games,
        "score": score,
        "score_fraction": fraction,
        "naive_elo_from_score": elo,
        "pair_histogram": dict(Counter(pair_scores)),
        "terminations": dict(Counter(str(row["termination"]) for row in rows)),
        "mean_python_game_move_ms": sum(py_means) / len(py_means) if py_means else None,
        "mean_rust_game_move_ms": sum(rust_means) / len(rust_means) if rust_means else None,
        "details": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps({k: v for k, v in result.items() if k != "details"}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
