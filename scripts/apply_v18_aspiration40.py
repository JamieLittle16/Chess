#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

replacements = [
('''    depth: int,\n    preferred: int,\n    nodes: np.ndarray,\n''', '''    depth: int,\n    preferred: int,\n    root_alpha: int,\n    root_beta: int,\n    nodes: np.ndarray,\n'''),
('''    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = -INFINITY\n''', '''    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = root_alpha\n    beta = root_beta\n'''),
('''                board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                -INFINITY, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,\n''', '''                board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                -beta, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,\n'''),
('''                    board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                    -INFINITY, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,\n''', '''                    board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                    -beta, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,\n'''),
('''        if score > alpha:\n            alpha = score\n    return best_move, best_score, False\n''', '''        if score > alpha:\n            alpha = score\n        if alpha >= beta:\n            break\n    return best_move, best_score, False\n'''),
('''            depth,\n            np.int64(best_move),\n            nodes,\n''', '''            depth,\n            np.int64(best_move),\n            np.int64(-INFINITY),\n            np.int64(INFINITY),\n            nodes,\n'''),
('''            board, side, castling, ep_square, halfmove_clock, depth, np.int64(best_move), nodes, hard_nodes,\n            0,\n''', '''            board, side, castling, ep_square, halfmove_clock, depth, np.int64(best_move),\n            np.int64(-INFINITY), np.int64(INFINITY), nodes, hard_nodes,\n            0,\n'''),
]
for old, new in replacements:
    if s.count(old) != 1:
        raise SystemExit(f'aspiration patch mismatch: {s.count(old)} for {old[:50]!r}')
    s = s.replace(old, new, 1)

old = '''        move, score, aborted = _root(\n            board, side, castling, ep_square, halfmove_clock, depth, np.int64(root_preferred), nodes, max_nodes,\n            hard_deadline,\n            pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count, path_keys,\n            killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n        )\n        if aborted:\n            break\n        now_ticks = int(_CPU_CLOCK())\n'''
new = '''        aspiration_alpha = -INFINITY\n        aspiration_beta = INFINITY\n        if depth >= 5 and completed_depth > 0 and abs(best_score) < MATE_THRESHOLD:\n            aspiration_alpha = max(-INFINITY, best_score - 40)\n            aspiration_beta = min(INFINITY, best_score + 40)\n        move, score, aborted = _root(\n            board, side, castling, ep_square, halfmove_clock, depth, np.int64(root_preferred),\n            np.int64(aspiration_alpha), np.int64(aspiration_beta), nodes, max_nodes,\n            hard_deadline,\n            pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count, path_keys,\n            killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n        )\n        if aborted:\n            break\n        if score <= aspiration_alpha or score >= aspiration_beta:\n            move, score, aborted = _root(\n                board, side, castling, ep_square, halfmove_clock, depth, np.int64(move),\n                np.int64(-INFINITY), np.int64(INFINITY), nodes, max_nodes, hard_deadline,\n                pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count, path_keys,\n                killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n                tt_table,\n            )\n            if aborted:\n                break\n        now_ticks = int(_CPU_CLOCK())\n'''
if s.count(old) != 1:
    raise SystemExit(f'timed aspiration patch mismatch: {s.count(old)}')
s = s.replace(old, new, 1)
p.write_text(s)
