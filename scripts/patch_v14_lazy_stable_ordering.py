#!/usr/bin/env python3
"""Replace eager stable insertion sorting with equivalent lazy stable prefix selection.

The patch preserves V13's exact score function and stable tie order.  It only delays ordering work
until a move is actually about to be searched, so beta cutoffs can avoid sorting the unused suffix.
Every fixed-node search signature must remain identical to qualified V13.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD_ORDER = '''@njit(cache=False)
def _order_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
) -> None:
    """Insertion-sort a legal move buffer by cheap tactical/PV priority."""
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

NEW_ORDER = '''@njit(cache=False)
def _order_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
) -> None:
    """Score legal moves; stable ordering is materialised lazily as the search consumes it."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)


@njit(cache=False, inline="always")
def _pick_next_scored_move(
    moves: np.ndarray,
    scores: np.ndarray,
    index: int,
    count: int,
) -> None:
    """Materialise exactly the next element of V13's stable descending insertion sort."""
    best = index
    best_score = int(scores[index])
    for candidate in range(index + 1, count):
        score = int(scores[candidate])
        # Strict greater-than preserves original generator order for equal scores.
        if score > best_score:
            best = candidate
            best_score = score
    if best == index:
        return

    best_move = int(moves[best])
    # Shift rather than swap so the still-unsorted suffix retains stable tie order.
    cursor = best
    while cursor > index:
        moves[cursor] = moves[cursor - 1]
        scores[cursor] = scores[cursor - 1]
        cursor -= 1
    moves[index] = best_move
    scores[index] = best_score
'''

OLD_KILLER_SORT = '''    for index in range(1, count):
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


def patch(path: Path) -> None:
    source = path.read_text()
    if "def _pick_next_scored_move(" in source:
        raise SystemExit("source already contains lazy stable ordering")
    if source.count(OLD_ORDER) != 1:
        raise SystemExit(f"ordinary order body count={source.count(OLD_ORDER)}")
    source = source.replace(OLD_ORDER, NEW_ORDER, 1)

    # After replacing _order_moves, exactly one identical insertion-sort body remains: killers.
    if source.count(OLD_KILLER_SORT) != 1:
        raise SystemExit(f"killer sort body count={source.count(OLD_KILLER_SORT)}")
    source = source.replace(OLD_KILLER_SORT, "", 1)

    # qsearch, recursive negamax, and root each consume one ordered buffer.
    loop_marker = "    for index in range(count):\n        move = int(moves[index])\n"
    loop_replacement = (
        "    for index in range(count):\n"
        "        _pick_next_scored_move(moves, score_stack[ply], index, count)\n"
        "        move = int(moves[index])\n"
    )
    # qsearch + negamax use score_stack[ply]. Root is handled separately below.
    if source.count(loop_marker) != 2:
        raise SystemExit(f"qsearch/negamax loop count={source.count(loop_marker)}")
    source = source.replace(loop_marker, loop_replacement, 2)

    root_marker = "    for index in range(count):\n        move = int(moves[index])\n        immediate_promotion = _is_immediate_promotion_threat(board, move)\n"
    root_replacement = (
        "    for index in range(count):\n"
        "        _pick_next_scored_move(moves, score_stack[0], index, count)\n"
        "        move = int(moves[index])\n"
        "        immediate_promotion = _is_immediate_promotion_threat(board, move)\n"
    )
    if source.count(root_marker) != 1:
        raise SystemExit(f"root loop count={source.count(root_marker)}")
    source = source.replace(root_marker, root_replacement, 1)

    if source.count("def _order_moves_with_killers(") != 1:
        raise SystemExit("killer ordering function missing")
    if "correction = correction // 6" not in source:
        raise SystemExit("qualified V13 1/6 residual baseline missing")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
