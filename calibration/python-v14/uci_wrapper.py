#!/usr/bin/env python3
"""Minimal UCI adapter for the exact Python V14 competition get_move API."""
from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE = Path(os.environ.get("PYTHON_V14_DIR", "/tmp/python-v14")).resolve()
sys.path.insert(0, str(PACKAGE))

import chess  # noqa: E402
import numpy as np  # noqa: E402
import agent  # noqa: E402

board = chess.Board()


def reset_agent() -> None:
    global board
    board = chess.Board()
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
        raise ValueError("empty position command")
    try:
        moves_index = tokens.index("moves")
    except ValueError:
        moves_index = len(tokens)

    if tokens[1] == "startpos":
        board = chess.Board()
        first_move = 2
    elif tokens[1] == "fen":
        fen = " ".join(tokens[2:moves_index])
        board = chess.Board(fen)
        first_move = moves_index
    else:
        raise ValueError(f"unsupported position form: {tokens[1]}")

    if moves_index < len(tokens):
        first_move = moves_index + 1
        for text in tokens[first_move:]:
            board.push_uci(text)


def go(tokens: list[str]) -> None:
    values: dict[str, int] = {}
    i = 1
    while i + 1 < len(tokens):
        key = tokens[i]
        if key in {"wtime", "btime", "winc", "binc", "movetime"}:
            try:
                values[key] = int(tokens[i + 1])
            except ValueError:
                pass
            i += 2
        else:
            i += 1

    if "movetime" in values:
        remaining = values["movetime"]
    else:
        remaining = values.get("wtime" if board.turn == chess.WHITE else "btime", 120_000)
    move = agent.get_move(board.fen(), max(1, remaining))
    if chess.Move.from_uci(move) not in board.legal_moves:
        raise RuntimeError(f"agent returned illegal move {move} in {board.fen()}")
    print(f"bestmove {move}", flush=True)


def main() -> None:
    reset_agent()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        tokens = line.split()
        cmd = tokens[0]
        try:
            if cmd == "uci":
                print("id name Little-Gambit-Python-V14-uploaded", flush=True)
                print("id author Jamie Little", flush=True)
                print("uciok", flush=True)
            elif cmd == "isready":
                print("readyok", flush=True)
            elif cmd == "ucinewgame":
                reset_agent()
            elif cmd == "position":
                set_position(tokens)
            elif cmd == "go":
                go(tokens)
            elif cmd == "quit":
                return
            elif cmd in {"setoption", "stop", "ponderhit", "debug"}:
                continue
        except Exception as exc:
            print(f"fatal Python V14 UCI error: {exc}", file=sys.stderr, flush=True)
            raise


if __name__ == "__main__":
    main()
