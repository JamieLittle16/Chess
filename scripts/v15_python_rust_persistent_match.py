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

    def move(
        self,
        root_fen: str,
        moves: list[str],
        white_ms: int,
        black_ms: int,
        inc_ms: int,
    ) -> tuple[str, float]:
        # Preserve the UCI move sequence rather than resetting from a freshly
        # synthesized FEN every ply. This is the path used by the Rust engine's
        # own repetition/context tests and retains all search history correctly.
        command = 'position fen ' + root_fen
        if moves:
            command += ' moves ' + ' '.join(moves)
        self._send(command)
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


def opening_fens(path: Path) -> list[str]:
    out: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        fields = line.split()
        if len(fields) >= 6 and fields[4].isdigit() and fields[5].isdigit():
            out.append(' '.join(fields[:6]))
        elif len(fields) >= 4:
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


def reset_python_game(agent: object) -> None:
    """Emulate the submission's fresh-process-per-game contract without re-JITing."""
    agent._GAME_KEYS = []
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(0)
    agent._HASH_MOVES.fill(-1)
    agent._TT_TABLE.fill(0)


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
    reset_python_game(agent)

    rust_env = os.environ.copy()
    rust = RustUCI(a.rust.resolve(), rust_env)
    games: list[dict[str, object]] = []
    py_score = 0.0
    wins = draws = losses = 0

    try:
        for opening_index, root_fen in enumerate(opening_fens(a.openings)):
            for python_white in (True, False):
                # Rust's ucinewgame reconstructs Engine search memory. Python's
                # official submission contract is one worker process per game,
                # so clear every mutable game/search cache here as the exact
                # in-process equivalent while retaining only compiled machine code.
                rust.new_game()
                reset_python_game(agent)
                board = chess.Board(root_fen)
                clocks = [float(a.base_ms), float(a.base_ms)]  # white, black
                reason = 'max-plies'
                result = '1/2-1/2'
                moves: list[str] = []
                ply_times: list[dict[str, object]] = []
                attempted_move: str | None = None

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
                        move_uci, elapsed = rust.move(
                            root_fen, moves, int(clocks[0]), int(clocks[1]), a.inc_ms
                        )

                    attempted_move = move_uci
                    clocks[side_idx] -= elapsed
                    actor = 'python' if is_python else 'rust'
                    ply_times.append({
                        'ply': ply + 1,
                        'actor': actor,
                        'elapsed_ms': elapsed,
                        'clock_before_ms': before,
                        'move': move_uci,
                    })

                    if clocks[side_idx] < 0:
                        # The side to move is the side that just consumed the
                        # measured time, so that side loses on a flag.
                        result = '0-1' if board.turn == chess.WHITE else '1-0'
                        reason = actor + '-flag'
                        break

                    try:
                        move = chess.Move.from_uci(move_uci)
                    except ValueError:
                        move = chess.Move.null()
                    if move not in board.legal_moves:
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
                    'root_fen': root_fen,
                    'python_white': python_white,
                    'result': result,
                    'python_score': val,
                    'reason': reason,
                    'attempted_move': attempted_move,
                    'plies': len(moves),
                    'final_fen': board.fen(),
                    'moves': moves,
                    'clocks_ms': clocks,
                    'times': ply_times,
                }
                games.append(rec)
                n = len(games)
                elo = elo_from_score(py_score, n)
                print(
                    f'GAME {n}: py_score={py_score:.1f}/{n} '
                    f'WDL={wins}-{draws}-{losses} reason={reason} elo={elo}',
                    flush=True,
                )
    finally:
        rust.close()

    elo = elo_from_score(py_score, len(games))
    summary = {
        'games': len(games),
        'python_score': py_score,
        'score_fraction': py_score / len(games) if games else None,
        'wins': wins,
        'draws': draws,
        'losses': losses,
        'python_elo_vs_rust': elo,
        'rust_elo_advantage': None if elo is None else -elo,
        'base_ms': a.base_ms,
        'inc_ms': a.inc_ms,
        'max_plies': a.max_plies,
        'python_state_reset_each_game': True,
    }
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps({'summary': summary, 'games_detail': games}, indent=2) + '\n')
    print('SUMMARY ' + json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
