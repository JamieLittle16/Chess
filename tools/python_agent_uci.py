#!/usr/bin/env python3
"""Minimal UCI shim around the Chessathon ``agent.get_move`` interface.

Usage: python tools/python_agent_uci.py /path/to/unpacked/engine

The shim intentionally delegates time allocation to the packaged agent.  It only translates UCI
position/clock commands into the competition API so Python-vs-Rust matches exercise the same Python
entry point used by the tournament.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import chess
import numpy as np

if len(sys.argv) != 2:
    raise SystemExit("usage: python_agent_uci.py ENGINE_DIR")
engine_dir = Path(sys.argv[1]).resolve()
if not (engine_dir / "agent.py").is_file():
    raise SystemExit(f"missing agent.py in {engine_dir}")
sys.path.insert(0, str(engine_dir))
agent = importlib.import_module("agent")
board = chess.Board()


def reset_agent() -> None:
    global board
    board = chess.Board()
    if hasattr(agent, "_GAME_KEYS"):
        agent._GAME_KEYS.clear()
    if hasattr(agent, "_PENDING_AFTER_OUR_MOVE"):
        agent._PENDING_AFTER_OUR_MOVE = None
    for name, value in (
        ("_LAST_CALL_TIME_LEFT_MS", None),
        ("_LAST_GET_MOVE_ELAPSED_MS", None),
        ("_CLOCK_OVERHEAD_EMA_MS", 40.0),
        ("_CLOCK_FEEDBACK_SAMPLES", 0),
    ):
        if hasattr(agent, name):
            setattr(agent, name, value)
    if hasattr(agent, "_HASH_KEYS"):
        agent._HASH_KEYS.fill(np.uint64(0))
    if hasattr(agent, "_HASH_MOVES"):
        agent._HASH_MOVES.fill(np.int32(-1))
    if hasattr(agent, "_TT_TABLE"):
        agent._TT_TABLE.fill(np.uint64(0))


def set_position(command: str) -> None:
    global board
    fields = command.split()
    if len(fields) < 2:
        return
    cursor = 1
    if fields[cursor] == "startpos":
        board = chess.Board()
        cursor += 1
    elif fields[cursor] == "fen":
        cursor += 1
        try:
            moves_index = fields.index("moves", cursor)
        except ValueError:
            moves_index = len(fields)
        fen = " ".join(fields[cursor:moves_index])
        board = chess.Board(fen)
        cursor = moves_index
    else:
        return
    if cursor < len(fields) and fields[cursor] == "moves":
        cursor += 1
        while cursor < len(fields):
            move = chess.Move.from_uci(fields[cursor])
            if move not in board.legal_moves:
                raise ValueError(f"illegal UCI position move {move} in {board.fen()}")
            board.push(move)
            cursor += 1


def own_time_ms(command: str) -> int:
    fields = command.split()[1:]
    values: dict[str, int] = {}
    i = 0
    while i < len(fields):
        key = fields[i]
        if key in {"wtime", "btime", "winc", "binc", "movetime", "movestogo"} and i + 1 < len(fields):
            try:
                values[key] = int(fields[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1
    if "movetime" in values:
        return max(1, values["movetime"])
    key = "wtime" if board.turn == chess.WHITE else "btime"
    return max(1, values.get(key, 120_000))


reset_agent()
for raw in sys.stdin:
    line = raw.strip()
    if not line:
        continue
    try:
        if line == "uci":
            print("id name Little Gambit Python competition API")
            print("id author Jamie Little")
            print("uciok", flush=True)
        elif line == "isready":
            print("readyok", flush=True)
        elif line.startswith("setoption "):
            # The competition package has fixed internal storage; Hash/Ponder options are ignored.
            continue
        elif line == "ucinewgame":
            reset_agent()
        elif line.startswith("position "):
            set_position(line)
        elif line.startswith("go"):
            remaining = own_time_ms(line)
            move_uci = str(agent.get_move(board.fen(), remaining))
            move = chess.Move.from_uci(move_uci)
            if move not in board.legal_moves:
                raise ValueError(f"agent returned illegal move {move_uci} in {board.fen()}")
            board.push(move)
            print(f"bestmove {move_uci}", flush=True)
        elif line == "stop":
            # get_move is synchronous and deadline-aware; there is no separate search worker.
            continue
        elif line == "quit":
            break
    except Exception as exc:
        print(f"info string python-agent-uci error: {type(exc).__name__}: {exc}", flush=True)
        print("bestmove 0000", flush=True)
