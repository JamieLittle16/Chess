#!/usr/bin/env python3
"""Convert V14 root prophylaxis A from absolute danger to candidate-created danger delta."""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = '''        if aborted:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            return best_move, best_score, True
        score = -score
        # Root-only consolidation bias. Apply only once search is non-trivial and the candidate is
        # not already losing; V13's aggressive counterplay remains untouched when behind.
        if depth >= 4 and score > 0 and score < MATE_THRESHOLD:
            danger = _root_prophylaxis_penalty(
                board, side, child_castling, child_ep, eval_stack[1],
                pseudo_stack[1], move_stack[1],
            )
            # Full prophylaxis weight in the common +0.5..+6 range. Very large winning scores get
            # half weight so a tactical conversion is not displaced by generic king neatness.
            if score > 600:
                danger = danger // 2
            score -= danger
        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
'''

NEW_TEMPLATE = '''        if aborted:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            return best_move, best_score, True
        score = -score
        # Measure only danger CREATED by this candidate (or removed by a consolidating candidate).
        # That is the actual rated-game failure mode and avoids penalising a sound position merely
        # because it already contains active pieces. Keep the mechanism live while only modestly
        # worse as well as when ahead: Round 62's ...Ne8 resource was defensive from about -1 pawn.
        if depth >= 4 and score > -300 and score < MATE_THRESHOLD:
            child_danger = _root_prophylaxis_penalty(
                board, side, child_castling, child_ep, eval_stack[1],
                pseudo_stack[1], move_stack[1],
            )
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            parent_danger = _root_prophylaxis_penalty(
                board, side, castling, ep_square, eval_stack[0],
                pseudo_stack[2], move_stack[2],
            )
            danger_delta = child_danger - parent_danger
            if danger_delta > 100:
                danger_delta = 100
            elif danger_delta < -100:
                danger_delta = -100
            adjustment = (danger_delta * __NUM__) // __DEN__
            if score > 600:
                adjustment = adjustment // 2
            score -= adjustment
        else:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
'''


def patch(path: Path, numerator: int, denominator: int) -> None:
    if denominator <= 0 or numerator <= 0:
        raise SystemExit('positive scale required')
    source = path.read_text()
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f'absolute prophylaxis block anchor drifted: {count}')
    new = NEW_TEMPLATE.replace('__NUM__', str(numerator)).replace('__DEN__', str(denominator))
    path.write_text(source.replace(OLD, new, 1))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path)
    p.add_argument('--numerator', type=int, required=True)
    p.add_argument('--denominator', type=int, required=True)
    a = p.parse_args()
    patch(a.path, a.numerator, a.denominator)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
