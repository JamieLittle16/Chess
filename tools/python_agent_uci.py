#!/usr/bin/env python3
"""Expose a packaged competition agent as a minimal synchronous UCI engine for A/B calibration."""
from __future__ import annotations

import os
import sys
from importlib import import_module

import chess
import numpy as np

if len(sys.argv) != 2:
    raise SystemExit("usage: python_agent_uci.py ENGINE_DIR")

# Keep all imported-agent diagnostics away from the UCI protocol stream.
protocol = os.fdopen(os.dup(1), "w", buffering=1)
os.dup2(2, 1)
sys.path.insert(0, sys.argv[1])
agent = import_module("agent")
board = chess.Board()


def reset_agent() -> None:
    agent._GAME_KEYS = []
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(np.uint64(0))
    agent._HASH_MOVES.fill(np.int32(-1))
    agent._TT_TABLE.fill(np.uint64(0))


def set_position(tokens: list[str]) -> None:
    global board
    if len(tokens) < 2:
        return
    if tokens[1] == "startpos":
        board = chess.Board()
        index = 2
    elif tokens[1] == "fen" and len(tokens) >= 8:
        board = chess.Board(" ".join(tokens[2:8]))
        index = 8
    else:
        return
    if index < len(tokens) and tokens[index] == "moves":
        for text in tokens[index + 1 :]:
            board.push_uci(text)


def go(tokens: list[str]) -> None:
    values: dict[str, int] = {}
    index = 1
    while index < len(tokens):
        key = tokens[index]
        if key in {"wtime", "btime", "winc", "binc", "movetime", "nodes", "depth"} and index + 1 < len(tokens):
            try:
                values[key] = int(tokens[index + 1])
            except ValueError:
                pass
            index += 2
        else:
            index += 1
    if "movetime" in values:
        remaining = values["movetime"]
    else:
        remaining = values.get("wtime" if board.turn == chess.WHITE else "btime", 2500)
    text = agent.get_move(board.fen(), max(0, remaining))
    move = chess.Move.from_uci(text)
    if move not in board.legal_moves:
        raise RuntimeError(f"agent returned illegal move {text} for {board.fen()}")
    protocol.write(f"bestmove {text}\n")


for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    tokens = line.split()
    cmd = tokens[0]
    if cmd == "uci":
        protocol.write("id name Little Gambit Python V16 candidate\n")
        protocol.write("id author Jamie Little\n")
        protocol.write("option name Hash type spin default 32 min 1 max 1024\n")
        protocol.write("uciok\n")
    elif cmd == "isready":
        protocol.write("readyok\n")
    elif cmd == "ucinewgame":
        reset_agent()
        board = chess.Board()
    elif cmd == "setoption":
        pass
    elif cmd == "position":
        set_position(tokens)
    elif cmd == "go":
        go(tokens)
    elif cmd == "stop":
        # The packaged agent is synchronous; Fastchess issues stop only after a timed go has returned.
        pass
    elif cmd == "quit":
        break
