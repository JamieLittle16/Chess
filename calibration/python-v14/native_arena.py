#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import numpy as np


def reset_python(agent) -> None:
    agent._GAME_KEYS = []
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(np.uint64(0))
    agent._HASH_MOVES.fill(np.int32(-1))
    agent._TT_TABLE.fill(np.uint64(0))


def load_openings(path: Path, indices: list[int]) -> list[tuple[int, chess.Board]]:
    lines = [x.strip() for x in path.read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')]
    out = []
    for idx in indices:
        # The frozen M6 suite stores full six-field FENs, not four-field EPD records.
        # Consume exactly the FEN fields so an accidental trailing annotation cannot alter the root.
        fields = lines[idx].split()
        if len(fields) < 6:
            raise ValueError(f"opening {idx} is not a six-field FEN: {lines[idx]!r}")
        board = chess.Board(" ".join(fields[:6]))
        out.append((idx, board))
    return out


def play_game(*, start: chess.Board, opening_index: int, python_color: chess.Color,
              agent, rust: chess.engine.SimpleEngine, rust_game_id: str,
              initial_ms: float, increment_ms: float, max_plies: int) -> tuple[dict, chess.pgn.Game]:
    reset_python(agent)
    board = start.copy(stack=False)
    clocks = {chess.WHITE: initial_ms, chess.BLACK: initial_ms}
    game = chess.pgn.Game.from_board(board)
    game.headers['Event'] = 'Python V14 vs Rust V15 native-clock calibration'
    game.headers['OpeningIndex'] = str(opening_index)
    game.headers['White'] = 'Python-V14-uploaded' if python_color == chess.WHITE else 'Rust-V15'
    game.headers['Black'] = 'Python-V14-uploaded' if python_color == chess.BLACK else 'Rust-V15'
    node = game
    reason = ''
    python_times = []
    rust_times = []

    for ply in range(max_plies):
        outcome = board.outcome(claim_draw=True)
        if outcome is not None:
            reason = outcome.termination.name
            break
        side = board.turn
        before = time.perf_counter()
        if side == python_color:
            move_text = agent.get_move(board.fen(), max(1, int(clocks[side])))
            elapsed_ms = (time.perf_counter() - before) * 1000.0
            move = chess.Move.from_uci(move_text)
            python_times.append(elapsed_ms)
        else:
            limit = chess.engine.Limit(
                white_clock=max(0.001, clocks[chess.WHITE] / 1000.0),
                black_clock=max(0.001, clocks[chess.BLACK] / 1000.0),
                white_inc=increment_ms / 1000.0,
                black_inc=increment_ms / 1000.0,
            )
            result = rust.play(board, limit, game=rust_game_id)
            elapsed_ms = (time.perf_counter() - before) * 1000.0
            move = result.move
            rust_times.append(elapsed_ms)

        clocks[side] -= elapsed_ms
        if clocks[side] < 0:
            winner = not side
            reason = 'TIME_FORFEIT_PYTHON' if side == python_color else 'TIME_FORFEIT_RUST'
            result_text = '1-0' if winner == chess.WHITE else '0-1'
            game.headers['Result'] = result_text
            game.headers['Termination'] = reason
            return ({
                'opening_index': opening_index, 'python_color': 'white' if python_color else 'black',
                'result': 'win' if winner == python_color else 'loss', 'reason': reason,
                'plies': ply, 'python_clock_ms': clocks[python_color], 'rust_clock_ms': clocks[not python_color],
                'python_mean_move_ms': sum(python_times)/len(python_times) if python_times else 0.0,
                'rust_mean_move_ms': sum(rust_times)/len(rust_times) if rust_times else 0.0,
            }, game)
        if move not in board.legal_moves:
            raise RuntimeError(f"illegal {'Python' if side == python_color else 'Rust'} move {move} in {board.fen()}")
        board.push(move)
        clocks[side] += increment_ms
        node = node.add_variation(move)
    else:
        reason = 'MAX_PLIES'

    outcome = board.outcome(claim_draw=True)
    if outcome is None:
        result_text = '1/2-1/2'
        py_result = 'draw'
    elif outcome.winner is None:
        result_text = '1/2-1/2'
        py_result = 'draw'
    else:
        result_text = '1-0' if outcome.winner == chess.WHITE else '0-1'
        py_result = 'win' if outcome.winner == python_color else 'loss'
    game.headers['Result'] = result_text
    game.headers['Termination'] = reason
    return ({
        'opening_index': opening_index, 'python_color': 'white' if python_color else 'black',
        'result': py_result, 'reason': reason, 'plies': board.ply(),
        'python_clock_ms': clocks[python_color], 'rust_clock_ms': clocks[not python_color],
        'python_mean_move_ms': sum(python_times)/len(python_times) if python_times else 0.0,
        'rust_mean_move_ms': sum(rust_times)/len(rust_times) if rust_times else 0.0,
    }, game)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--python-dir', type=Path, required=True)
    ap.add_argument('--rust', type=Path, required=True)
    ap.add_argument('--gestalt', type=Path, required=True)
    ap.add_argument('--openings', type=Path, required=True)
    ap.add_argument('--indices', required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--initial-ms', type=float, default=120000.0)
    ap.add_argument('--increment-ms', type=float, default=500.0)
    ap.add_argument('--max-plies', type=int, default=600)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(args.python_dir.resolve()))
    # This import performs V14's intentional free-window JIT compilation before any clock starts.
    import agent

    indices = [int(x) for x in args.indices.split(',')]
    openings = load_openings(args.openings, indices)
    env = os.environ.copy()
    env['CHESS_GESTALT_NETWORK'] = str(args.gestalt.resolve())
    rust = chess.engine.SimpleEngine.popen_uci(str(args.rust.resolve()), timeout=30.0, env=env)
    try:
        if 'Hash' in rust.options:
            rust.configure({'Hash': 32})
        rows = []
        games = []
        for opening_index, start in openings:
            for py_color in (chess.WHITE, chess.BLACK):
                gid = f"opening-{opening_index}-py-{'w' if py_color else 'b'}"
                row, game = play_game(start=start, opening_index=opening_index, python_color=py_color,
                                      agent=agent, rust=rust, rust_game_id=gid,
                                      initial_ms=args.initial_ms, increment_ms=args.increment_ms,
                                      max_plies=args.max_plies)
                rows.append(row)
                games.append(game)
                print(json.dumps(row, sort_keys=True), flush=True)
    finally:
        rust.quit()

    summary = {
        'games': len(rows),
        'wins': sum(r['result'] == 'win' for r in rows),
        'draws': sum(r['result'] == 'draw' for r in rows),
        'losses': sum(r['result'] == 'loss' for r in rows),
        'rows': rows,
    }
    (args.output_dir / 'results.json').write_text(json.dumps(summary, indent=2) + '\n')
    with (args.output_dir / 'games.pgn').open('w') as fh:
        exporter = chess.pgn.FileExporter(fh)
        for game in games:
            game.accept(exporter)
    print('SUMMARY ' + json.dumps({k: summary[k] for k in ('games','wins','draws','losses')}, sort_keys=True), flush=True)

if __name__ == '__main__':
    main()
