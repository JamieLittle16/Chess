#!/usr/bin/env python3
"""Competition-API A/B on the eight published rated-ladder roots, both candidate colours."""
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
from pathlib import Path

import chess

OPENINGS = [
    "r1bqk2r/pp1pppbp/2n2np1/2p5/2P5/2N1PNP1/PP1P1PBP/R1BQK2R b KQkq - 0 6",
    "r1b1k2r/pp2nppp/2n1p3/q1ppP3/P2P4/2P2N2/2PB1PPP/R2QKB1R b KQkq - 4 9",
    "rnbqkb1r/pp3ppp/2p5/1B1p4/3Pn3/5N2/PPP2PPP/RNBQK2R w KQkq - 0 7",
    "r1bq1rk1/pppp1ppp/2n2n2/1Bb5/3NP3/2P5/PP3PPP/RNBQ1RK1 w - - 3 8",
    "rnbqk2r/pp2ppbp/6p1/2p5/3PP3/2P1BN2/P4PPP/R2QKB1R b KQkq - 1 8",
    "r1bqk2r/pp1n1ppp/2n1p3/2bpP3/5P2/2NB4/PPP3PP/R1BQK1NR w KQkq - 0 8",
    "1rbqk1nr/pp2ppbp/2np2p1/2p5/P3P3/2NP2P1/1PP1NPBP/R1BQK2R b KQk - 0 7",
    "r1bqkb1r/pp3ppp/2np4/1N1Pp3/8/8/PPP2PPP/R1BQKB1R b KQkq - 0 8",
]


def key(board: chess.Board) -> str:
    return " ".join(board.fen(en_passant="fen").split()[:4])


class Agent:
    def __init__(self, directory: str, runner: str):
        self.p = subprocess.Popen(
            [sys.executable, runner, directory], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self.q: queue.Queue[str | None] = queue.Queue()
        self.err: list[str] = []
        threading.Thread(target=self._out, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()
        assert json.loads(self._line(120)).get("ready") is True

    def _out(self):
        assert self.p.stdout is not None
        for line in self.p.stdout:
            self.q.put(line.rstrip("\n"))
        self.q.put(None)

    def _stderr(self):
        assert self.p.stderr is not None
        for line in self.p.stderr:
            self.err.append(line.rstrip("\n"))

    def _line(self, timeout: float) -> str:
        try:
            line = self.q.get(timeout=timeout)
        except queue.Empty as exc:
            raise RuntimeError("agent timeout") from exc
        if line is None:
            raise RuntimeError("agent closed: " + "\n".join(self.err[-20:]))
        return line

    def reset(self):
        assert self.p.stdin is not None
        self.p.stdin.write(json.dumps({"reset": True}) + "\n"); self.p.stdin.flush()
        assert json.loads(self._line(5)).get("reset") is True

    def move(self, board: chess.Board, ms: float) -> tuple[chess.Move, float]:
        assert self.p.stdin is not None
        start = time.monotonic()
        self.p.stdin.write(json.dumps({"fen": board.fen(), "time_left_ms": max(0, int(ms))}) + "\n")
        self.p.stdin.flush()
        row = json.loads(self._line((max(0.0, ms) + 1500.0) / 1000.0))
        elapsed = (time.monotonic() - start) * 1000.0
        move = chess.Move.from_uci(row["move"])
        if move not in board.legal_moves:
            raise RuntimeError(f"illegal move {move}")
        return move, elapsed

    def stop(self):
        if self.p.poll() is None:
            self.p.kill()
        self.p.wait(timeout=5)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    ap.add_argument("control")
    ap.add_argument("--runner", default="tools/v14_agent_runner.py")
    ap.add_argument("--book", type=Path, required=True)
    ap.add_argument("--base-ms", type=int, default=2500)
    ap.add_argument("--inc-ms", type=int, default=50)
    ap.add_argument("--max-plies", type=int, default=180)
    ap.add_argument("--json-out", type=Path, required=True)
    args = ap.parse_args()
    entries = json.loads(args.book.read_text())["entries"]
    cand = Agent(args.candidate, args.runner); base = Agent(args.control, args.runner)
    rows = []
    try:
        for oi, fen in enumerate(OPENINGS):
            root = chess.Board(fen)
            for candidate_color in (root.turn, not root.turn):
                b = chess.Board(fen); clocks = {chess.WHITE: float(args.base_ms), chess.BLACK: float(args.base_ms)}
                cand.reset(); base.reset(); booked = 0; cand_moves = 0; cand_ms = []; base_ms = []
                result = None
                for _ in range(args.max_plies):
                    outcome = b.outcome(claim_draw=True)
                    if outcome is not None:
                        result = 0.5 if outcome.winner is None else float(outcome.winner == candidate_color)
                        termination = b.result(claim_draw=True); break
                    side = b.turn; use_cand = side == candidate_color; engine = cand if use_cand else base
                    book_uci = entries.get(key(b)) if use_cand else None
                    try:
                        move, elapsed = engine.move(b, clocks[side])
                    except Exception as exc:
                        result = 0.0 if use_cand else 1.0; termination = f"engine-failure:{type(exc).__name__}"; break
                    clocks[side] -= elapsed
                    if clocks[side] < 0:
                        result = 0.0 if use_cand else 1.0; termination = "flag"; break
                    if use_cand:
                        cand_moves += 1; cand_ms.append(elapsed)
                        if book_uci == move.uci(): booked += 1
                    else:
                        base_ms.append(elapsed)
                    b.push(move); clocks[side] += args.inc_ms
                else:
                    result = 0.5; termination = "max-ply-draw"
                row = {"opening": oi, "candidate_color": "white" if candidate_color else "black",
                       "score": result, "termination": termination, "booked_candidate_plies": booked,
                       "candidate_moves": cand_moves, "candidate_mean_ms": sum(cand_ms)/max(1,len(cand_ms)),
                       "control_mean_ms": sum(base_ms)/max(1,len(base_ms))}
                rows.append(row); print(json.dumps(row), flush=True)
    finally:
        cand.stop(); base.stop()
    score = sum(float(r["score"]) for r in rows); n = len(rows); frac = score / n
    elo = 400 * math.log10(frac / (1-frac)) if 0 < frac < 1 else None
    out = {"games": n, "score": score, "score_fraction": frac, "naive_elo_from_score": elo,
           "booked_candidate_plies": sum(r["booked_candidate_plies"] for r in rows),
           "candidate_moves": sum(r["candidate_moves"] for r in rows), "details": rows}
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(out, indent=2) + "\n")
    print("FINAL", json.dumps({k:v for k,v in out.items() if k != "details"}), flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
