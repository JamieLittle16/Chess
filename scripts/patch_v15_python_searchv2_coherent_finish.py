#!/usr/bin/env python3
"""Finish the coherent Python Search-v2 transplant after the history patch is applied.

This removes the Python-specific O(n^2) lazy next-best scans, preserving the same stable score
ordering with one insertion sort, and fixes signed gravity arithmetic to Rust's truncation-toward-zero
semantics. It intentionally changes no history thresholds or LMR policy.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_searchv2_coherent_finish.py SEARCH.py")
p=Path(sys.argv[1]); s=p.read_text()

old='''    gravity = current * abs(bonus) // HISTORY_LIMIT
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
'''
new='''    product = current * abs(bonus)
    gravity = product // HISTORY_LIMIT if product >= 0 else -((-product) // HISTORY_LIMIT)
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
'''
if s.count(old)!=1: raise SystemExit(f'gravity anchor count={s.count(old)}')
s=s.replace(old,new,1)

# Checked qsearch and tactical qsearch use _order_moves. Materialise its stable score order once.
old='''    """Score legal moves; stable ordering is materialised lazily as search consumes it."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
'''
new='''    """Score legal moves once, then materialise stable descending order once."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
    for index in range(1, count):
        move = int(moves[index]); score = int(scores[index]); cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]; scores[cursor + 1] = scores[cursor]; cursor -= 1
        moves[cursor + 1] = move; scores[cursor + 1] = score
'''
if s.count(old)!=1: raise SystemExit(f'plain order anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''        scores[index] = score


@njit(cache=False)
def _order_root_moves_with_history(
'''
new='''        scores[index] = score
    for index in range(1, count):
        move = int(moves[index]); score = int(scores[index]); cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]; scores[cursor + 1] = scores[cursor]; cursor -= 1
        moves[cursor + 1] = move; scores[cursor + 1] = score


@njit(cache=False)
def _order_root_moves_with_history(
'''
if s.count(old)!=1: raise SystemExit(f'history order tail count={s.count(old)}')
s=s.replace(old,new,1)

old='''        scores[index] = score



@njit(cache=False)
def _is_tactical'''
new='''        scores[index] = score
    for index in range(1, count):
        move = int(moves[index]); score = int(scores[index]); cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]; scores[cursor + 1] = scores[cursor]; cursor -= 1
        moves[cursor + 1] = move; scores[cursor + 1] = score



@njit(cache=False)
def _is_tactical'''
if s.count(old)!=1: raise SystemExit(f'root history order tail count={s.count(old)}')
s=s.replace(old,new,1)

# All three consumers now receive fully ordered lists: qsearch, negamax, and root.
ply_pick='        _pick_next_scored_move(moves, score_stack[ply], index, count)\n'
if s.count(ply_pick)!=2: raise SystemExit(f'ply pick count={s.count(ply_pick)}')
s=s.replace(ply_pick,'')
root_pick='        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
if s.count(root_pick)!=1: raise SystemExit(f'root pick count={s.count(root_pick)}')
s=s.replace(root_pick,'')

p.write_text(s)
