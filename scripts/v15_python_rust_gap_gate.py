#!/usr/bin/env python3
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
from collections import Counter, deque
from pathlib import Path

import chess


class PythonAgent:
    def __init__(self, root: str, runner: str):
        self.p = subprocess.Popen(
            [sys.executable, runner, root],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.q: queue.Queue[str | None] = queue.Queue()
        self.err: deque[str] = deque(maxlen=100)
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()
        if json.loads(self._line(95)).get("ready") is not True:
            raise RuntimeError("Python agent did not become ready")

    def _out(self) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def _err(self) -> None:
        assert self.p.stderr is not None
        for line in self.p.stderr:
            self.err.append(line.rstrip("\n"))

    def _line(self, timeout: float) -> str:
        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("Python agent timeout") from exc
        if line is None:
            raise RuntimeError("Python agent closed: " + "\n".join(self.err))
        return line

    def reset(self) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write('{"reset":true}\n')
        self.p.stdin.flush()
        if json.loads(self._line(5)).get("reset") is not True:
            raise RuntimeError("Python agent reset failed")

    def move(self, board: chess.Board, remaining_ms: float, grace_ms: int) -> chess.Move:
        assert self.p.stdin is not None
        self.p.stdin.write(
            json.dumps({"fen": board.fen(), "time_left_ms": max(0, int(remaining_ms))}) + "\n"
        )
        self.p.stdin.flush()
        response = json.loads(self._line((max(0.0, remaining_ms) + grace_ms) / 1000.0))
        move = chess.Move.from_uci(response["move"])
        if move not in board.legal_moves:
            raise RuntimeError(f"illegal Python move {move.uci()}")
        return move

    def stop(self) -> None:
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait(timeout=5)


class RustUci:
    def __init__(self, binary: str, network: str, hash_mb: int):
        env = os.environ.copy()
        env["CHESS_GESTALT_NETWORK"] = str(Path(network).resolve())
        self.p = subprocess.Popen(
            [binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        self.q: queue.Queue[str | None] = queue.Queue()
        self.err: deque[str] = deque(maxlen=100)
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._err, daemon=True).start()
        self._send("uci")
        self._wait_token("uciok", 10)
        self._send(f"setoption name Hash value {hash_mb}")
        self._ready()

    def _out(self) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def _err(self) -> None:
        assert self.p.stderr is not None
        for line in self.p.stderr:
            self.err.append(line.rstrip("\n"))

    def _send(self, text: str) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(text + "\n")
        self.p.stdin.flush()

    def _line(self, timeout: float) -> str:
        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("Rust UCI timeout") from exc
        if line is None:
            raise RuntimeError("Rust UCI closed: " + "\n".join(self.err))
        return line

    def _wait_token(self, token: str, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"Rust UCI timeout waiting for {token}")
            line = self._line(remaining)
            if line == token or line.startswith(token):
                return line

    def _ready(self) -> None:
        self._send("isready")
        self._wait_token("readyok", 10)

    def reset(self) -> None:
        self._send("ucinewgame")
        self._ready()

    def move(
        self,
        board: chess.Board,
        clocks: dict[chess.Color, float],
        inc_ms: int,
        grace_ms: int,
    ) -> chess.Move:
        self._send(f"position fen {board.fen()}")
        self._send(
            "go "
            f"wtime {max(0, int(clocks[chess.WHITE]))} "
            f"btime {max(0, int(clocks[chess.BLACK]))} "
            f"winc {inc_ms} binc {inc_ms}"
        )
        deadline = time.monotonic() + (max(5_000.0, clocks[board.turn]) + grace_ms) / 1000.0
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError("Rust UCI bestmove timeout")
            line = self._line(remaining)
            if not line.startswith("bestmove "):
                continue
            token = line.split()[1]
            move = chess.Move.from_uci(token)
            if move not in board.legal_moves:
                raise RuntimeError(f"illegal Rust move {move.uci()}")
            return move

    def stop(self) -> None:
        if self.p.poll() is None:
            try:
                self._send("quit")
                self.p.wait(timeout=2)
            except Exception:
                self.p.kill()
        self.p.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True)
    parser.add_argument("--rust", required=True)
    parser.add_argument("--network", required=True)
    parser.add_argument("--openings", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--label", required=True)
    parser.add_argument("--base-ms", type=int, default=10_000)
    parser.add_argument("--inc-ms", type=int, default=500)
    parser.add_argument("--max-plies", type=int, default=180)
    parser.add_argument("--grace-ms", type=int, default=1_500)
    parser.add_argument("--hash-mb", type=int, default=32)
    parser.add_argument("--runner", default="tools/v14_agent_runner.py")
    args = parser.parse_args()

    roots = [x.strip() for x in Path(args.openings).read_text().splitlines() if x.strip()]
    py = PythonAgent(args.python, args.runner)
    rust = RustUci(args.rust, args.network, args.hash_mb)
    rows: list[dict[str, object]] = []
    pairs: list[float] = []

    def play(fen: str, python_white: bool) -> tuple[float, str, list[tuple[bool, float]]]:
        board = chess.Board(fen)
        clocks = {chess.WHITE: float(args.base_ms), chess.BLACK: float(args.base_ms)}
        py.reset()
        rust.reset()
        timings: list[tuple[bool, float]] = []
        py_color = chess.WHITE if python_white else chess.BLACK
        for _ in range(args.max_plies):
            outcome = board.outcome(claim_draw=True)
            if outcome is not None:
                score = 0.5 if outcome.winner is None else float(outcome.winner == py_color)
                return score, board.result(claim_draw=True), timings
            side = board.turn
            use_python = side == py_color
            started = time.monotonic()
            try:
                if use_python:
                    move = py.move(board, clocks[side], args.grace_ms)
                else:
                    move = rust.move(board, clocks, args.inc_ms, args.grace_ms)
            except Exception as exc:
                return (
                    (0.0 if use_python else 1.0),
                    f"engine-failure:{'python' if use_python else 'rust'}:{type(exc).__name__}",
                    timings,
                )
            elapsed_ms = (time.monotonic() - started) * 1000.0
            clocks[side] -= elapsed_ms
            if clocks[side] < 0:
                return (0.0 if use_python else 1.0), f"flag:{'python' if use_python else 'rust'}", timings
            timings.append((use_python, elapsed_ms))
            board.push(move)
            clocks[side] += args.inc_ms
        return 0.5, "max-ply-draw", timings

    try:
        for opening_index, fen in enumerate(roots):
            pair_score = 0.0
            for python_white in (True, False):
                score, result, timings = play(fen, python_white)
                pair_score += score
                row = {
                    "opening": opening_index,
                    "python_white": python_white,
                    "score": score,
                    "result": result,
                    "python_ms": [x for is_python, x in timings if is_python],
                    "rust_ms": [x for is_python, x in timings if not is_python],
                }
                rows.append(row)
                print(opening_index, python_white, score, result, flush=True)
            pairs.append(pair_score)
    finally:
        py.stop()
        rust.stop()

    score = sum(float(row["score"]) for row in rows)
    games = len(rows)
    fraction = score / games
    elo = 400.0 * math.log10(fraction / (1.0 - fraction)) if 0.0 < fraction < 1.0 else None
    py_times = [v for row in rows for v in row["python_ms"]]
    rust_times = [v for row in rows for v in row["rust_ms"]]
    summary = {
        "python": args.label,
        "rust": "final V15 3a6a194 + certified Gestalt",
        "games": games,
        "score": score,
        "score_fraction": fraction,
        "naive_python_elo_vs_rust": elo,
        "pair_histogram": dict(Counter(str(x) for x in pairs)),
        "python_mean_move_ms": sum(py_times) / max(1, len(py_times)),
        "rust_mean_move_ms": sum(rust_times) / max(1, len(rust_times)),
        "details": rows,
    }
    Path(args.output).write_text(json.dumps(summary, indent=2) + "\n")
    print("FINAL", json.dumps({k: v for k, v in summary.items() if k != "details"}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
