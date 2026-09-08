#!/usr/bin/env python3
"""Replace eager stable insertion sorting with equivalent lazy stable prefix selection.

The patch preserves V13's exact score function and stable tie order. It only delays ordering work
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
    """Score legal moves; stable ordering is materialised lazily as search consumes it."""
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
        if score > best_score:
            best = candidate
            best_score = score
    if best == index:
        return
    best_move = int(moves[best])
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

QSEARCH_LOOP = '''    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
QSEARCH_LAZY = '''    for index in range(count):
        _pick_next_scored_move(moves, score_stack[ply], index, count)
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''

NEGAMAX_LOOP = '''    for index in range(count):
        move = int(moves[index])
        order_score = int(score_stack[ply, index])
'''
NEGAMAX_LAZY = '''    for index in range(count):
        _pick_next_scored_move(moves, score_stack[ply], index, count)
        move = int(moves[index])
        order_score = int(score_stack[ply, index])
'''

ROOT_LOOP = '''    for index in range(count):
        if nodes[0] >= max_nodes:
            return best_move, best_score, True
        if hard_deadline_ticks > 0 and (int(nodes[0]) & _TIME_CHECK_MASK) == 0:
            if int(_CPU_CLOCK()) >= hard_deadline_ticks:
                return best_move, best_score, True
        move = int(moves[index])
'''
ROOT_LAZY = '''    for index in range(count):
        if nodes[0] >= max_nodes:
            return best_move, best_score, True
        if hard_deadline_ticks > 0 and (int(nodes[0]) & _TIME_CHECK_MASK) == 0:
            if int(_CPU_CLOCK()) >= hard_deadline_ticks:
                return best_move, best_score, True
        _pick_next_scored_move(moves, score_stack[0], index, count)
        move = int(moves[index])
'''


def replace_one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one occurrence, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()
    if "def _pick_next_scored_move(" in source:
        raise SystemExit("source already contains lazy stable ordering")
    source = replace_one(source, OLD_ORDER, NEW_ORDER, "ordinary ordering")
    source = replace_one(source, OLD_KILLER_SORT, "", "killer ordering")
    source = replace_one(source, QSEARCH_LOOP, QSEARCH_LAZY, "qsearch loop")
    source = replace_one(source, NEGAMAX_LOOP, NEGAMAX_LAZY, "negamax loop")
    source = replace_one(source, ROOT_LOOP, ROOT_LAZY, "root loop")
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
