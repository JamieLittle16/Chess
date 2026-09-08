#!/usr/bin/env python3
"""Refine the Search-v2 history port with Rust-style staged move selection.

Assumes patch_v15_searchv2_history.py has already been applied to packaged V14. The replacement
keeps TT/tactical/killer priority, then ranks ordinary quiets by the already-added main+continuation
history in one cached pass. This removes repeated full-list history comparisons from the recursive
hot path and matches the accepted Rust Search-v2 picker semantics much more closely.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_staged_history_picker.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''    _order_moves_with_killers(
        board,
        side,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
        previous_move_context,
        main_history,
        continuation_history,
    )

    best_score = -INFINITY
    best_move = -1
    for index in range(count):
        _pick_next_scored_move(moves, score_stack[ply], index, count)
        move = int(moves[index])
        order_score = int(score_stack[ply, index])
'''
new = '''    # Rust Search-v2 staged picker: TT/tacticals first, then the two quiet killers, then rank
    # the untouched ordinary quiet suffix exactly once by main+continuation history.  The old Python
    # port rescored/scanned the entire remaining set for every move, which was both slower and not
    # semantically identical to the accepted Rust mechanism.
    scores = score_stack[ply]
    side_index = 0 if side == WHITE else 1
    for raw_index in range(count):
        move = int(moves[raw_index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == int(killers[ply, 0]):
                score += 5_000_000
            elif move == int(killers[ply, 1]):
                score += 4_900_000
            elif not _is_tactical(board, move):
                context = _move_history_context(board, move)
                score += int(main_history[side_index, context])
                if previous_move_context >= 0:
                    score += int(continuation_history[previous_move_context, context])
        scores[raw_index] = score

    best_score = -INFINITY
    best_move = -1
    for index in range(count):
        # Stable one-pass materialisation of the next staged element.  The score bands enforce
        # TT > tactical > killers > ordinary quiets; within the quiet band history determines rank.
        _pick_next_scored_move(moves, scores, index, count)
        move = int(moves[index])
        order_score = int(scores[index])
'''
if s.count(old) != 1:
    raise SystemExit(f"picker anchor count={s.count(old)}")
s = s.replace(old, new, 1)

# The first refinement is intentionally conservative: keep the proven stable selector while
# removing the duplicated helper call and ensure each quiet history score is computed once per
# generated node.  A later lane may replace the selector with a dedicated staged partition after
# this semantics-preserving step has been measured.
p.write_text(s)
