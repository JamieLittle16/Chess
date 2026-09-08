#!/usr/bin/env python3
"""Add fail-soft aspiration windows to exact packaged V14 fixed-node iterative search.

The root receives an explicit alpha/beta window. Iterative deepening searches around the previous
completed score from depth four onward, doubling the window on fail-low/fail-high until the score is
inside it (or the full window is restored). No move is intentionally omitted: this is a search-cost
experiment, with the existing node ceiling remaining the only interruption mechanism.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_aspiration.py SEARCH.py WINDOW_CP")
p = Path(sys.argv[1])
window_cp = int(sys.argv[2])
if window_cp <= 0:
    raise SystemExit("WINDOW_CP must be positive")
s = p.read_text()

def once(old: str, new: str, label: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"{label}: expected one anchor, found {n}")
    s = s.replace(old, new, 1)

once(
    """    depth: int,\n    preferred: int,\n    nodes: np.ndarray,""",
    """    depth: int,\n    preferred: int,\n    root_alpha: int,\n    root_beta: int,\n    nodes: np.ndarray,""",
    "root signature",
)
once(
    """    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = -INFINITY\n""",
    """    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = root_alpha\n""",
    "root alpha",
)

root_start = s.index("def _root(")
root_end = s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful(", root_start)
head, root, tail = s[:root_start], s[root_start:root_end], s[root_end:]
old_window = "                -INFINITY, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,"
if root.count(old_window) != 2:
    raise SystemExit(f"root full-window anchors: expected 2, found {root.count(old_window)}")
root = root.replace(
    old_window,
    "                -root_beta, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,",
)
old_cut = """        if score > alpha:\n            alpha = score\n    return best_move, best_score, False\n"""
new_cut = """        if score > alpha:\n            alpha = score\n            if alpha >= root_beta:\n                break\n    return best_move, best_score, False\n"""
if root.count(old_cut) != 1:
    raise SystemExit(f"root cutoff anchor count={root.count(old_cut)}")
root = root.replace(old_cut, new_cut, 1)
s = head + root + tail

once(
    """            depth,\n            best_move,\n            nodes,""",
    """            depth,\n            best_move,\n            -INFINITY,\n            INFINITY,\n            nodes,""",
    "fixed full-window call",
)
once(
    """            board, side, castling, ep_square, halfmove_clock, depth, best_move, nodes, hard_nodes,\n            0,""",
    """            board, side, castling, ep_square, halfmove_clock, depth, best_move, -INFINITY, INFINITY, nodes, hard_nodes,\n            0,""",
    "adaptive full-window call",
)
once(
    """            board, side, castling, ep_square, halfmove_clock, depth, best_move, nodes, max_nodes,\n            hard_deadline,""",
    """            board, side, castling, ep_square, halfmove_clock, depth, best_move, -INFINITY, INFINITY, nodes, max_nodes,\n            hard_deadline,""",
    "timed full-window call",
)

old_call = """        move, score, aborted = _root(\n            board,\n            side,\n            castling,\n            ep_square,\n            halfmove_clock,\n            depth,\n            best_move,\n            -INFINITY,\n            INFINITY,\n            nodes,\n            max_nodes,\n            hard_deadline_ticks,\n            pseudo_stack,\n            move_stack,\n            score_stack,\n            eval_stack,\n            history_keys,\n            history_count,\n            path_keys,\n            killers,\n            hash_keys,\n            hash_moves,\n            history_contexts,\n            tt_table,\n        )\n"""
new_call = f"""        aspiration = {window_cp} if depth >= 4 and abs(best_score) < MATE_THRESHOLD else INFINITY\n        root_alpha = max(-INFINITY, best_score - aspiration) if aspiration < INFINITY else -INFINITY\n        root_beta = min(INFINITY, best_score + aspiration) if aspiration < INFINITY else INFINITY\n        while True:\n            move, score, aborted = _root(\n                board, side, castling, ep_square, halfmove_clock, depth, best_move,\n                root_alpha, root_beta, nodes, max_nodes, hard_deadline_ticks,\n                pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count,\n                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,\n            )\n            if aborted or aspiration >= INFINITY:\n                break\n            if score <= root_alpha or score >= root_beta:\n                aspiration = min(INFINITY, aspiration * 2)\n                root_alpha = max(-INFINITY, best_score - aspiration)\n                root_beta = min(INFINITY, best_score + aspiration)\n                continue\n            break\n"""
once(old_call, new_call, "fixed iterative aspiration wrapper")

p.write_text(s)
