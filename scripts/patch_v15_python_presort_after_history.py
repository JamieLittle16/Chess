#!/usr/bin/env python3
"""Materialise move ordering once after the Search-v2 history patch.

The first Python history/LMR port retained V14's repeated next-best scans, so it paid O(n^2)
selection overhead while adding history work. This patch preserves the history scores exactly but
stable-sorts each generated move list once, matching the already-qualified one-pass ordering
transformation and letting search consume moves linearly.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_presort_after_history.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()


def rep(old: str, new: str, n: int, label: str) -> None:
    global s
    count = s.count(old)
    if count != n:
        raise SystemExit(f"{label} count={count} expected={n}")
    s = s.replace(old, new, n)

sort_tail = '''    for index in range(1, count):
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

old = '''    """Score legal moves; stable ordering is materialised lazily as search consumes it."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
'''
new = '''    """Score legal moves once, then materialise stable descending order once."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
''' + sort_tail
rep(old, new, 1, "ordinary ordering")

old = '''    """Order PV/tacticals, killers, then ordinary quiets by main+continuation history."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            elif not _is_tactical(board, move):
                context = _move_history_context(board, move)
                score += _history_score(
                    side, previous_context, context, main_history, continuation_history
                )
        scores[index] = score
'''
new = old + sort_tail
rep(old, new, 1, "history ordering")

old = '''    """Root ordering uses side-specific main history; there is no predecessor context."""
    side_index = 0 if side == WHITE else 1
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000 and not _is_tactical(board, move):
            context = _move_history_context(board, move)
            score += int(main_history[side_index, context])
        scores[index] = score
'''
new = old + sort_tail
rep(old, new, 1, "root history ordering")

# qsearch has two ply-indexed lazy-pick sites; normal search has one more.  All now consume sorted lists.
old = '        _pick_next_scored_move(moves, score_stack[ply], index, count)\n'
count = s.count(old)
if count not in (2, 3):
    raise SystemExit(f"ply lazy-pick count={count}, expected 2 or 3")
s = s.replace(old, '')
old = '        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
if s.count(old) != 1:
    raise SystemExit(f"root lazy-pick count={s.count(old)} expected=1")
s = s.replace(old, '', 1)

p.write_text(s)
