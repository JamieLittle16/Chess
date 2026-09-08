#!/usr/bin/env python3
"""Patch exact V13 with a conservative bounded SEE-like bad-capture ordering classifier.

This experiment changes ordering only. It never removes a move, changes qsearch membership, alters
legality, changes evaluation, or introduces SEE pruning. Preferred/TT moves retain absolute priority.
Only non-promotion captures of a lower-valued victim by a higher-valued attacker pay the exchange
probe; checking captures are left in V13's original tactical band. Clearly negative exchanges are
moved behind the two quiet killers but remain ahead of ordinary quiets.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()

    source = replace_once(
        source,
        """    BISHOP,
    EMPTY,
""",
        """    BISHOP,
    BISHOP_DIRS,
    EMPTY,
""",
        "bishop directions import",
    )
    source = replace_once(
        source,
        """    KING,
    KNIGHT,
    MAX_MOVES,
""",
        """    KING,
    KING_TARGETS,
    KING_TARGET_COUNTS,
    KNIGHT,
    KNIGHT_TARGETS,
    KNIGHT_TARGET_COUNTS,
    MAX_MOVES,
""",
        "leaper tables import",
    )
    source = replace_once(
        source,
        """    QUEEN,
    ROOK,
    WHITE,
""",
        """    QUEEN,
    ROOK,
    ROOK_DIRS,
    WHITE,
""",
        "rook directions import",
    )
    source = replace_once(
        source,
        """    is_square_attacked,
    make_move_inplace,
""",
        """    is_square_attacked,
    king_square,
    make_move_inplace,
""",
        "king square import",
    )

    anchor = """@njit(cache=False)
def _move_order_score(board: np.ndarray, move: int, preferred: int) -> int:
"""
    helpers = r'''@njit(cache=False, inline="always")
def _see_first_slider(
    board: np.ndarray,
    target: int,
    side: int,
    piece_a: int,
    piece_b: int,
    diagonal: bool,
) -> int:
    target_file = target & 7
    target_rank = target >> 3
    directions = BISHOP_DIRS if diagonal else ROOK_DIRS
    for delta_file, delta_rank in directions:
        source_file = target_file + delta_file
        source_rank = target_rank + delta_rank
        while 0 <= source_file < 8 and 0 <= source_rank < 8:
            source = source_rank * 8 + source_file
            signed_piece = int(board[source])
            if signed_piece != EMPTY:
                piece = abs(signed_piece)
                if signed_piece * side > 0 and (piece == piece_a or piece == piece_b):
                    return source
                break
            source_file += delta_file
            source_rank += delta_rank
    return -1


@njit(cache=False, inline="always")
def _see_least_attacker(board: np.ndarray, target: int, side: int) -> int:
    """Return a least-valued pseudo-attacker of ``target`` for bounded exchange ordering."""
    target_file = target & 7
    target_rank = target >> 3

    source_rank = target_rank - side
    if 0 <= source_rank < 8:
        left_file = target_file - 1
        if left_file >= 0:
            source = source_rank * 8 + left_file
            if int(board[source]) == side * PAWN:
                return source
        right_file = target_file + 1
        if right_file < 8:
            source = source_rank * 8 + right_file
            if int(board[source]) == side * PAWN:
                return source

    for index in range(int(KNIGHT_TARGET_COUNTS[target])):
        source = int(KNIGHT_TARGETS[target, index])
        if int(board[source]) == side * KNIGHT:
            return source

    source = _see_first_slider(board, target, side, BISHOP, BISHOP, True)
    if source >= 0:
        return source
    source = _see_first_slider(board, target, side, ROOK, ROOK, False)
    if source >= 0:
        return source
    source = _see_first_slider(board, target, side, QUEEN, QUEEN, True)
    if source >= 0:
        return source
    source = _see_first_slider(board, target, side, QUEEN, QUEEN, False)
    if source >= 0:
        return source

    for index in range(int(KING_TARGET_COUNTS[target])):
        source = int(KING_TARGETS[target, index])
        if int(board[source]) == side * KING:
            return source
    return -1


@njit(cache=False)
def _see_reply_gain(
    board: np.ndarray,
    target: int,
    side: int,
    target_value: int,
    remaining: int,
) -> int:
    """Bounded least-attacker exchange gain for the side that may recapture next."""
    if remaining <= 0:
        return 0
    source = _see_least_attacker(board, target, side)
    if source < 0:
        return 0

    attacker = int(board[source])
    attacker_value = int(PIECE_VALUE[abs(attacker)])
    previous_target = int(board[target])
    board[source] = EMPTY
    board[target] = attacker

    # A king may not capture onto an attacked square. Other pinned-pseudo-attacker inaccuracies are
    # tolerated because this is ordering-only and we require a meaningful negative margin below.
    if abs(attacker) == KING and is_square_attacked(board, target, -side):
        board[source] = attacker
        board[target] = previous_target
        return 0

    response = _see_reply_gain(board, target, -side, attacker_value, remaining - 1)
    board[source] = attacker
    board[target] = previous_target

    gain = target_value - response
    return gain if gain > 0 else 0


@njit(cache=False)
def _bounded_capture_see(board: np.ndarray, move: int, target_value: int) -> int:
    """Approximate material result of an adverse-MVV capture without changing search semantics."""
    from_square = move_from(move)
    to_square = move_to(move)
    moving = int(board[from_square])
    side = WHITE if moving > 0 else -WHITE
    moving_value = int(PIECE_VALUE[abs(moving)])
    captured = int(board[to_square])

    board[from_square] = EMPTY
    board[to_square] = moving

    # Never demote a forcing checking capture in this first conservative ordering experiment.
    opponent_king = king_square(board, -side)
    if opponent_king >= 0 and is_square_attacked(board, opponent_king, side):
        board[from_square] = moving
        board[to_square] = captured
        return 0

    reply_gain = _see_reply_gain(board, to_square, -side, moving_value, 4)
    board[from_square] = moving
    board[to_square] = captured
    return target_value - reply_gain


@njit(cache=False)
def _move_order_score(board: np.ndarray, move: int, preferred: int) -> int:
'''
    source = replace_once(source, anchor, helpers, "move-order helper insertion")

    source = replace_once(
        source,
        """    if target:
        score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])
    if promotion:
""",
        """    if target:
        score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])
        # Cheap gate: favorable/equal MVV captures cannot have negative first-order material SEE,
        # so only probe higher-valued pieces taking lower-valued victims. Promotions retain V13
        # ordering because promotion exchange accounting deserves a separate experiment.
        if promotion == 0 and int(PIECE_VALUE[target]) < int(PIECE_VALUE[attacker]):
            exchange = _bounded_capture_see(board, move, int(PIECE_VALUE[target]))
            if exchange < -50:
                score -= 2_200_000
    if promotion:
""",
        "bad capture demotion",
    )

    required = (
        "_bounded_capture_see",
        "_see_reply_gain",
        "score -= 2_200_000",
        "king_square",
    )
    for marker in required:
        if marker not in source:
            raise SystemExit(f"missing SEE marker after patch: {marker}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
