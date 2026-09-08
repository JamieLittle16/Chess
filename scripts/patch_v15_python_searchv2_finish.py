#!/usr/bin/env python3
"""Finish the Python Search-v2 transplant with Rust-exact gravity and one-pass ordering.

Apply this after patch_v15_python_searchv2_history.py. The first history probe retained V14's
O(n^2) repeated next-best scans and Python-floor division for negative history gravity. Rust V15
uses truncating signed division and consumes an already-ranked quiet batch linearly. This patch
removes those two Python-only distortions while preserving stable score ties.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_searchv2_finish.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = """    gravity = current * abs(bonus) // HISTORY_LIMIT
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
"""
new = """    product = current * abs(bonus)
    # Rust signed integer division truncates toward zero; Python // floors negatives.
    gravity = product // HISTORY_LIMIT if product >= 0 else -((-product) // HISTORY_LIMIT)
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
"""
if s.count(old) != 1:
    raise SystemExit(f"gravity anchor count={s.count(old)}")
s = s.replace(old, new, 1)

sort_body = """    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
"""

# Ordinary qsearch/root score helper: score once, stable sort once.
old = """    \"\"\"Score legal moves; stable ordering is materialised lazily as search consumes it.\"\"\"
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
"""
new = """    \"\"\"Score legal moves once and materialise stable descending order once.\"\"\"
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
""" + sort_body
if s.count(old) != 1:
    raise SystemExit(f"ordinary order anchor count={s.count(old)}")
s = s.replace(old, new, 1)

# History-aware interior ordering.
needle = """        scores[index] = score


@njit(cache=False)
def _order_root_moves_with_history(
"""
replacement = """        scores[index] = score
""" + sort_body + """

@njit(cache=False)
def _order_root_moves_with_history(
"""
if s.count(needle) != 1:
    raise SystemExit(f"history interior order anchor count={s.count(needle)}")
s = s.replace(needle, replacement, 1)

# History-aware root ordering.
needle = """            score += int(main_history[side_index, context])
        scores[index] = score



@njit(cache=False)
def _is_tactical"""
replacement = """            score += int(main_history[side_index, context])
        scores[index] = score
""" + sort_body + """


@njit(cache=False)
def _is_tactical"""
if s.count(needle) != 1:
    raise SystemExit(f"history root order anchor count={s.count(needle)}")
s = s.replace(needle, replacement, 1)

# Search now consumes the pre-ranked arrays linearly. qsearch has two ply-indexed paths, normal
# search one, and root one; the first history patch leaves all three repeated-selection calls alive.
old = '        _pick_next_scored_move(moves, score_stack[ply], index, count)\n'
if s.count(old) != 2:
    raise SystemExit(f"ply repeated-pick count={s.count(old)}")
s = s.replace(old, '')
old = '        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
if s.count(old) != 1:
    raise SystemExit(f"root repeated-pick count={s.count(old)}")
s = s.replace(old, '')

p.write_text(s)
