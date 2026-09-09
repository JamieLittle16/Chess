#!/usr/bin/env python3
"""Add conservative iterative-deepening aspiration windows to the Rust-history Python stack.

Apply after patch_v16_python_presort_once.py and patch_v16_python_rust_history.py.  Depths 1-3 keep
the exact full-window root search.  From depth 4 onward the previous completed score centres a small
root window; fail-low/high doubles the window and eventually falls back to [-INFINITY, INFINITY].
Failed attempts consume the ordinary node/time budget and keep their TT/history work, just as they
would in a production alpha-beta search.
"""
from pathlib import Path
import sys

if len(sys.argv) not in (2, 3):
    raise SystemExit("usage: patch_v16_python_aspiration.py SEARCH.py [INITIAL_CP]")
path = Path(sys.argv[1])
initial = int(sys.argv[2]) if len(sys.argv) == 3 else 50
if initial < 16 or initial > 400:
    raise SystemExit("INITIAL_CP must be in [16, 400]")
s = path.read_text()

old = '''@njit(cache=False)
def _root(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    halfmove_clock: int,
    depth: int,
    preferred: int,
    nodes: np.ndarray,'''
new = '''@njit(cache=False)
def _root_window(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    halfmove_clock: int,
    depth: int,
    preferred: int,
    root_alpha: int,
    root_beta: int,
    nodes: np.ndarray,'''
if s.count(old) != 1:
    raise SystemExit(f"root signature anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    best_move = int(moves[0])
    best_score = -INFINITY
    alpha = -INFINITY
'''
new = '''    best_move = int(moves[0])
    best_score = -INFINITY
    alpha = root_alpha
'''
if s.count(old) != 1:
    raise SystemExit(f"root alpha anchor count={s.count(old)}")
s = s.replace(old, new, 1)

root_start = s.index("def _root_window(")
root_end = s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful(", root_start)
root = s[root_start:root_end]
full_child = "                -INFINITY, -alpha, 1,"
if root.count(full_child) != 2:
    raise SystemExit(f"root full-child window count={root.count(full_child)}")
root = root.replace(full_child, "                -root_beta, -alpha, 1,")
old = '''        if score > alpha:
            alpha = score
    return best_move, best_score, False
'''
new = '''        if score > alpha:
            alpha = score
        if alpha >= root_beta:
            break
    return best_move, best_score, False
'''
if root.count(old) != 1:
    raise SystemExit(f"root cutoff anchor count={root.count(old)}")
root = root.replace(old, new, 1)
s = s[:root_start] + root + s[root_end:]

anchor = '''

@njit(cache=False)
def iterative_search_stateful(
'''
wrapper = f'''

ASPIRATION_MIN_DEPTH = 4
ASPIRATION_INITIAL = {initial}
ASPIRATION_FULL_WIDTH = 1600


@njit(cache=False)
def _root(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    halfmove_clock: int,
    depth: int,
    preferred: int,
    previous_score: int,
    nodes: np.ndarray,
    max_nodes: int,
    hard_deadline_ticks: int,
    pseudo_stack: np.ndarray,
    move_stack: np.ndarray,
    score_stack: np.ndarray,
    eval_stack: np.ndarray,
    history_keys: np.ndarray,
    history_count: int,
    path_keys: np.ndarray,
    killers: np.ndarray,
    hash_keys: np.ndarray,
    hash_moves: np.ndarray,
    history_contexts: np.ndarray,
    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
) -> tuple[int, int, bool]:
    if depth < ASPIRATION_MIN_DEPTH or abs(previous_score) >= MATE_THRESHOLD:
        return _root_window(
            board, side, castling, ep_square, halfmove_clock, depth, preferred,
            -INFINITY, INFINITY, nodes, max_nodes, hard_deadline_ticks,
            pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count,
            path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table, quiet_history,
            move_context_stack,
        )

    width = ASPIRATION_INITIAL
    while width < ASPIRATION_FULL_WIDTH:
        root_alpha = max(-INFINITY, previous_score - width)
        root_beta = min(INFINITY, previous_score + width)
        move, score, aborted = _root_window(
            board, side, castling, ep_square, halfmove_clock, depth, preferred,
            root_alpha, root_beta, nodes, max_nodes, hard_deadline_ticks,
            pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count,
            path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table, quiet_history,
            move_context_stack,
        )
        if aborted:
            return move, score, True
        if score > root_alpha and score < root_beta:
            return move, score, False
        # Let the best move from the failed pass lead the widened re-search.
        preferred = move
        width *= 2

    return _root_window(
        board, side, castling, ep_square, halfmove_clock, depth, preferred,
        -INFINITY, INFINITY, nodes, max_nodes, hard_deadline_ticks,
        pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count,
        path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table, quiet_history,
        move_context_stack,
    )
''' + anchor
if s.count(anchor) != 1:
    raise SystemExit(f"iterative insertion anchor count={s.count(anchor)}")
s = s.replace(anchor, wrapper, 1)

old = '''            depth,
            best_move,
            nodes,'''
new = '''            depth,
            best_move,
            best_score,
            nodes,'''
if s.count(old) != 1:
    raise SystemExit(f"stateful root-call anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "board, side, castling, ep_square, halfmove_clock, depth, best_move, nodes, hard_nodes,"
new = "board, side, castling, ep_square, halfmove_clock, depth, best_move, best_score, nodes, hard_nodes,"
if s.count(old) != 1:
    raise SystemExit(f"adaptive root-call anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "board, side, castling, ep_square, halfmove_clock, depth, best_move, nodes, max_nodes,"
new = "board, side, castling, ep_square, halfmove_clock, depth, best_move, best_score, nodes, max_nodes,"
if s.count(old) != 1:
    raise SystemExit(f"timed root-call anchor count={s.count(old)}")
s = s.replace(old, new, 1)

path.write_text(s)
print(f"applied depth>=4 aspiration windows: initial={initial}cp, full fallback=1600cp")
