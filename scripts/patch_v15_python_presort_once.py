#!/usr/bin/env python3
"""Replace V14's repeated next-best scans with one stable in-place score sort per move list.

Search semantics are intended to remain identical: the same move scores are used and equal scores
retain generator order. The change only materialises the full stable descending order once, so
search can consume it linearly instead of performing an O(n^2) next-maximum scan at every node.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_presort_once.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''    """Score legal moves; stable ordering is materialised lazily as search consumes it."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
'''
new = '''    """Score legal moves once, then materialise the stable descending order once."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
'''
if s.count(old) != 1:
    raise SystemExit(f"ordinary order anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    """Order PV/tacticals first, then two quiet killers, then ordinary quiets."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
        scores[index] = score
'''
new = '''    """Order PV/tacticals, killers and quiets once; search then consumes linearly."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
        scores[index] = score
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
'''
if s.count(old) != 1:
    raise SystemExit(f"killer order anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '        _pick_next_scored_move(moves, score_stack[ply], index, count)\n'
if s.count(old) != 2:
    raise SystemExit(f"ply next-pick count={s.count(old)}")
s = s.replace(old, '')
old = '        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
if s.count(old) != 1:
    raise SystemExit(f"root next-pick count={s.count(old)}")
s = s.replace(old, '')

p.write_text(s)
