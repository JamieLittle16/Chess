#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

import chess


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument('--python-dir', type=Path, required=True)
    p.add_argument('--rust', type=Path, required=True)
    p.add_argument('--openings', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--base-ms', type=int, default=10000)
    p.add_argument('--inc-ms', type=int, default=500)
    p.add_argument('--max-plies', type=int, default=180)
    return p.parse_args()


class RustUCI:
    def __init__(self, exe: Path, env: dict[str, str]) -> None:
        self.p = subprocess.Popen(
            [str(exe)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
        )
        assert self.p.stdin is not None and self.p.stdout is not None
        self._send('uci')
        self._wait('uciok')
        self._send('isready')
        self._wait('readyok')

    def _send(self, line: str) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(line + '\n')
        self.p.stdin.flush()

    def _wait(self, prefix: str) -> str:
        assert self.p.stdout is not None
        while True:
            line = self.p.stdout.readline()
            if line == '':
                raise RuntimeError(f'Rust engine exited while waiting for {prefix!r}')
            line = line.strip()
            if line.startswith(prefix):
                return line

    def new_game(self) -> None:
        self._send('ucinewgame')
        self._send('isready')
        self._wait('readyok')

    def move(self, board: chess.Board, white_ms: int, black_ms: int, inc_ms: int) -> tuple[str, float]:
        self._send('position fen ' + board.fen())
        self._send(f'go wtime {max(1, white_ms)} btime {max(1, black_ms)} winc {inc_ms} binc {inc_ms}')
        started = time.perf_counter()
        line = self._wait('bestmove ')
        elapsed = (time.perf_counter() - started) * 1000.0
        parts = line.split()
        if len(parts) < 2:
            raise RuntimeError('malformed bestmove: ' + line)
        return parts[1], elapsed

    def close(self) -> None:
        try:
            self._send('quit')
        except Exception:
            pass
        try:
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


def epd_fens(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) < 4:
            continue
        out.append(' '.join(fields[:4]) + ' 0 1')
    return out


def elo_from_score(score: float, games: int) -> float | None:
    if games <= 0:
        return None
    p = score / games
    if p <= 0.0 or p >= 1.0:
        return None
    return 400.0 * math.log10(p / (1.0 - p))


def result_value(result: str, python_white: bool) -> float:
    if result == '1/2-1/2':
        return 0.5
    if result == '1-0':
        return 1.0 if python_white else 0.0
    if result == '0-1':
        return 0.0 if python_white else 1.0
    raise ValueError(result)


def main() -> int:
    a = parse_args()
    python_dir = a.python_dir.resolve()
    sys.path.insert(0, str(python_dir))
    agent = importlib.import_module('agent')

    # Pay Numba import/JIT cost exactly once, outside all game clocks.
    warm_fens = [
        chess.STARTING_FEN,
        '2r3k1/4qp2/4b3/p5p1/4P1P1/2Pr2P1/P4PB1/R1Q2RK1 w - - 1 23',
    ]
    for fen in warm_fens:
        mv = agent.get_move(fen, 80000)
        if chess.Move.from_uci(mv) not in chess.Board(fen).legal_moves:
            raise RuntimeError('Python warmup returned illegal move ' + mv)

    rust_env = os.environ.copy()
    rust = RustUCI(a.rust.resolve(), rust_env)
    games: list[dict[str, object]] = []
    py_score = 0.0
    wins = draws = losses = 0

    try:
        for opening_index, fen in enumerate(epd_fens(a.openings)):
            for python_white in (True, False):
                rust.new_game()
                board = chess.Board(fen)
                clocks = [a.base_ms, a.base_ms]  # white, black
                reason = 'max-plies'
                result = '1/2-1/2'
                moves: list[str] = []
                ply_times: list[dict[str, object]] = []

                for ply in range(a.max_plies):
                    if board.is_game_over(claim_draw=True):
                        result = board.result(claim_draw=True)
                        reason = 'board-result'
                        break

                    is_python = (board.turn == chess.WHITE) == python_white
                    side_idx = 0 if board.turn == chess.WHITE else 1
                    before = clocks[side_idx]
                    if is_python:
                        started = time.perf_counter()
                        move_uci = agent.get_move(board.fen(), max(1, int(before)))
                        elapsed = (time.perf_counter() - started) * 1000.0
                    else:
                        move_uci, elapsed = rust.move(board, clocks[0], clocks[1], a.inc_ms)

                    clocks[side_idx] -= elapsed
                    actor = 'python' if is_python else 'rust'
                    ply_times.append({'ply': ply + 1, 'actor': actor, 'elapsed_ms': elapsed, 'clock_before_ms': before})

                    if clocks[side_idx] < 0:
                        python_lost = is_python
                        result = '0-1' if board.turn == chess.WHITE else '1-0'
                        if not python_lost:
                            result = '1-0' if board.turn == chess.WHITE else '0-1'
                        reason = actor + '-flag'
                        break

                    try:
                        move = chess.Move.from_uci(move_uci)
                    except ValueError:
                        move = chess.Move.null()
                    if move not in board.legal_moves:
                        # Illegal move loses immediately.
                        result = '0-1' if board.turn == chess.WHITE else '1-0'
                        reason = actor + '-illegal'
                        break

                    board.push(move)
                    clocks[side_idx] += a.inc_ms
                    moves.append(move_uci)
                else:
                    result = '1/2-1/2'

                val = result_value(result, python_white)
                py_score += val
                if val == 1.0:
                    wins += 1
                elif val == 0.5:
                    draws += 1
                else:
                    losses += 1
                rec = {
                    'opening_index': opening_index,
                    'python_white': python_white,
                    'result': result,
                    'python_score': val,
                    'reason': reason,
                    'plies': len(moves),
                    'final_fen': board.fen(),
                    'moves': moves,
                    'clocks_ms': clocks,
                    'times': ply_times,
                }
                games.append(rec)
                n = len(games)
                elo = elo_from_score(py_score, n)
                print(f'GAME {n}: py_score={py_score:.1f}/{n} WDL={wins}-{draws}-{losses} elo={elo}', flush=True)
    finally:
        rust.close()

    summary = {
        'games': len(games),
        'python_score': py_score,
        'score_fraction': py_score / len(games) if games else None,
        'wins': wins,
        'draws': draws,
        'losses': losses,
        'python_elo_vs_rust': elo_from_score(py_score, len(games)),
        'rust_elo_advantage': None if elo_from_score(py_score, len(games)) is None else -elo_from_score(py_score, len(games)),
        'base_ms': a.base_ms,
        'inc_ms': a.inc_ms,
        'max_plies': a.max_plies,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'summary': summary, 'games_detail': games}, indent=2) + '\n')
    print('SUMMARY ' + json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
