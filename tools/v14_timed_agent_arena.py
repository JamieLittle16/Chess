#!/usr/bin/env python3
"""Run paired colour-swapped production get_move games between two packaged Python agents."""
from __future__ import annotations

import argparse
from collections import Counter, deque
import json
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import chess


class AgentProcess:
    def __init__(self, directory: str, init_timeout: float) -> None:
        self.proc = subprocess.Popen(
            [sys.executable, "tools/v14_agent_runner.py", directory],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr: deque[str] = deque(maxlen=100)
        threading.Thread(target=self._read_out, daemon=True).start()
        threading.Thread(target=self._read_err, daemon=True).start()
        payload = json.loads(self._line(init_timeout))
        if payload.get("ready") is not True:
            raise RuntimeError(f"agent did not become ready: {payload}")

    def _read_out(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)

    def _read_err(self) -> None:
        assert self.proc.stderr is not None
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip("\n"))

    def _line(self, timeout: float) -> str:
        try:
            line = self.lines.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("agent protocol timeout") from exc
        if line is None:
            raise RuntimeError("agent protocol closed: " + "\n".join(self.stderr))
        return line

    def reset(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"reset": True}) + "\n")
        self.proc.stdin.flush()
        payload = json.loads(self._line(5.0))
        if payload.get("reset") is not True:
            raise RuntimeError(payload)

    def move(self, board: chess.Board, clock_ms: float, grace_ms: int) -> tuple[chess.Move, float]:
        assert self.proc.stdin is not None
        self.proc.stdin.write(
            json.dumps({"fen": board.fen(), "time_left_ms": max(0, int(clock_ms))}) + "\n"
        )
        self.proc.stdin.flush()
        started = time.monotonic()
        payload = json.loads(self._line((max(0.0, clock_ms) + grace_ms) / 1000.0))
        elapsed = (time.monotonic() - started) * 1000.0
        move = chess.Move.from_uci(payload["move"])
        if move not in board.legal_moves:
            raise RuntimeError((board.fen(), payload))
        return move, elapsed

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.kill()
        self.proc.wait(timeout=5)


def load_openings(path: Path, offset: int, pairs: int) -> list[str]:
    rows = [line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]
    selected = rows[offset : offset + pairs]
    if len(selected) != pairs:
        raise SystemExit(f"need {pairs} openings at offset {offset}, found {len(selected)}")
    return selected


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("candidate")
    p.add_argument("control")
    p.add_argument("--opening-file", type=Path, required=True)
    p.add_argument("--opening-offset", type=int, default=0)
    p.add_argument("--pairs", type=int, default=32)
    p.add_argument("--base-ms", type=int, default=2500)
    p.add_argument("--increment-ms", type=int, default=50)
    p.add_argument("--max-plies", type=int, default=180)
    p.add_argument("--watchdog-grace-ms", type=int, default=1200)
    p.add_argument("--init-timeout", type=float, default=95.0)
    p.add_argument("--json-out", type=Path, required=True)
    args = p.parse_args()

    openings = load_openings(args.opening_file, args.opening_offset, args.pairs)
    control = AgentProcess(args.control, args.init_timeout)
    candidate = AgentProcess(args.candidate, args.init_timeout)

    def play(fen: str, candidate_white: bool):
        board = chess.Board(fen)
        clocks = {chess.WHITE: float(args.base_ms), chess.BLACK: float(args.base_ms)}
        control.reset()
        candidate.reset()
        timings: list[dict[str, float | bool]] = []
        for _ in range(args.max_plies):
            outcome = board.outcome(claim_draw=True)
            if outcome is not None:
                if outcome.winner is None:
                    return 0.5, board.result(claim_draw=True), board.ply(), clocks, timings
                return (
                    1.0 if outcome.winner == candidate_white else 0.0,
                    board.result(claim_draw=True),
                    board.ply(),
                    clocks,
                    timings,
                )
            mover = board.turn
            use_candidate = mover == candidate_white
            engine = candidate if use_candidate else control
            try:
                move, elapsed = engine.move(board, clocks[mover], args.watchdog_grace_ms)
            except Exception as exc:  # test harness must score crashes/timeout as losses
                return (
                    0.0 if use_candidate else 1.0,
                    f"engine-failure:{type(exc).__name__}",
                    board.ply(),
                    clocks,
                    timings,
                )
            clocks[mover] -= elapsed
            if clocks[mover] < 0:
                return (
                    0.0 if use_candidate else 1.0,
                    "flag",
                    board.ply(),
                    clocks,
                    timings,
                )
            timings.append({"candidate": use_candidate, "elapsed_ms": elapsed})
            board.push(move)
            clocks[mover] += args.increment_ms
        return 0.5, "max-ply-draw", board.ply(), clocks, timings

    rows = []
    pair_scores = []
    try:
        for idx, fen in enumerate(openings):
            pair = 0.0
            for candidate_white in (True, False):
                score, result, plies, clocks, timings = play(fen, candidate_white)
                pair += score
                row = {
                    "opening": idx + args.opening_offset,
                    "candidate_white": candidate_white,
                    "candidate_score": score,
                    "result": result,
                    "plies": plies,
                    "candidate_move_ms": [
                        round(float(t["elapsed_ms"]), 3) for t in timings if bool(t["candidate"])
                    ],
                    "control_move_ms": [
                        round(float(t["elapsed_ms"]), 3) for t in timings if not bool(t["candidate"])
                    ],
                }
                rows.append(row)
                print({k: v for k, v in row.items() if not k.endswith("_move_ms")}, flush=True)
            pair_scores.append(pair)
    finally:
        control.stop()
        candidate.stop()

    total = sum(float(row["candidate_score"]) for row in rows)
    games = len(rows)
    fraction = total / games
    elo = 400.0 * math.log10(fraction / (1.0 - fraction)) if 0.0 < fraction < 1.0 else None
    ct = [x for row in rows for x in row["candidate_move_ms"]]
    bt = [x for row in rows for x in row["control_move_ms"]]
    summary = {
        "candidate": args.candidate,
        "control": args.control,
        "time_control_ms": [args.base_ms, args.increment_ms],
        "games": games,
        "score": total,
        "score_fraction": fraction,
        "naive_elo_from_score": elo,
        "pair_score_histogram": dict(Counter(str(x) for x in pair_scores)),
        "terminations": dict(Counter(str(row["result"]) for row in rows)),
        "candidate_mean_move_ms": sum(ct) / max(1, len(ct)),
        "control_mean_move_ms": sum(bt) / max(1, len(bt)),
        "games_detail": rows,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, indent=2) + "\n")
    print("FINAL", json.dumps({k: v for k, v in summary.items() if k != "games_detail"}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
