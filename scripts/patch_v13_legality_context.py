#!/usr/bin/env python3
"""Patch exact V13 Numba move generation with a shared king-safety legality context.

Ordinary non-king/non-en-passant moves are decided from node-local check and pin facts. King moves,
castles and en-passant retain V13's exact make/attack/unmake oracle. Pseudo move generation and legal
move order are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

HELPERS = r'''@njit(cache=False, inline="always")
def _mask_has(mask: np.uint64, square: int) -> bool:
    return (mask & (np.uint64(1) << np.uint64(square))) != 0


@njit(cache=False, inline="always")
def _squares_collinear(origin: int, through: int, target: int) -> bool:
    origin_file = origin & 7
    origin_rank = origin >> 3
    through_file = (through & 7) - origin_file
    through_rank = (through >> 3) - origin_rank
    target_file = (target & 7) - origin_file
    target_rank = (target >> 3) - origin_rank
    return through_file * target_rank == through_rank * target_file


@njit(cache=False, inline="always")
def _between_aligned(origin: int, target: int, square: int) -> bool:
    origin_file = origin & 7
    origin_rank = origin >> 3
    target_file = target & 7
    target_rank = target >> 3
    square_file = square & 7
    square_rank = square >> 3
    file_delta = target_file - origin_file
    rank_delta = target_rank - origin_rank
    if file_delta != 0 and rank_delta != 0 and abs(file_delta) != abs(rank_delta):
        return False
    if not _squares_collinear(origin, target, square):
        return False
    return (
        min(origin_file, target_file) <= square_file <= max(origin_file, target_file)
        and min(origin_rank, target_rank) <= square_rank <= max(origin_rank, target_rank)
        and square != origin
        and square != target
    )


@njit(cache=False, inline="never")
def _legality_context(
    board: np.ndarray,
    side: int,
    own_king: int,
) -> tuple[int, int, int, np.uint64]:
    """Return ``(check_count, checker_square, checker_is_slider, pinned_mask)``."""
    if own_king < 0:
        return 2, -1, 0, np.uint64(0)

    enemy = -side
    king_file = own_king & 7
    king_rank = own_king >> 3
    check_count = 0
    checker_square = -1
    checker_is_slider = 0
    pinned = np.uint64(0)

    # Pawn attacks onto our king.
    source_rank = king_rank - enemy
    if 0 <= source_rank < 8:
        for delta_file in (-1, 1):
            source_file = king_file - delta_file
            if 0 <= source_file < 8:
                source = _square(source_file, source_rank)
                if int(board[source]) == enemy * PAWN:
                    check_count += 1
                    checker_square = source
                    checker_is_slider = 0

    # Leaper checkers.
    for index in range(int(KNIGHT_TARGET_COUNTS[own_king])):
        source = int(KNIGHT_TARGETS[own_king, index])
        if int(board[source]) == enemy * KNIGHT:
            check_count += 1
            checker_square = source
            checker_is_slider = 0
    for index in range(int(KING_TARGET_COUNTS[own_king])):
        source = int(KING_TARGETS[own_king, index])
        if int(board[source]) == enemy * KING:
            check_count += 1
            checker_square = source
            checker_is_slider = 0

    # Slider checkers and absolute pins. Scan each king ray once.
    for family in range(2):
        directions = BISHOP_DIRS if family == 0 else ROOK_DIRS
        for delta_file, delta_rank in directions:
            file = king_file + delta_file
            rank = king_rank + delta_rank
            blocker = -1
            while _inside(file, rank):
                square = _square(file, rank)
                signed_piece = int(board[square])
                if signed_piece == EMPTY:
                    file += delta_file
                    rank += delta_rank
                    continue
                if signed_piece * side > 0:
                    if blocker < 0:
                        blocker = square
                        file += delta_file
                        rank += delta_rank
                        continue
                    break

                kind = abs(signed_piece)
                slider = (
                    kind == QUEEN
                    or (family == 0 and kind == BISHOP)
                    or (family == 1 and kind == ROOK)
                )
                if slider:
                    if blocker < 0:
                        check_count += 1
                        checker_square = square
                        checker_is_slider = 1
                    else:
                        pinned |= np.uint64(1) << np.uint64(blocker)
                break

    return check_count, checker_square, checker_is_slider, pinned


@njit(cache=False, inline="always")
def _ordinary_legal_with_context(
    move: int,
    own_king: int,
    check_count: int,
    checker_square: int,
    checker_is_slider: int,
    pinned: np.uint64,
) -> bool:
    if check_count >= 2:
        return False

    from_square = move_from(move)
    to_square = move_to(move)
    if check_count == 1 and to_square != checker_square:
        if checker_is_slider == 0 or not _between_aligned(
            own_king, checker_square, to_square
        ):
            return False

    if _mask_has(pinned, from_square) and not _squares_collinear(
        own_king, from_square, to_square
    ):
        return False
    return True


'''

REPLACEMENT = r'''@njit(cache=False)
def generate_legal_moves_into_with_king(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    pseudo: np.ndarray,
    legal: np.ndarray,
    own_king: int,
) -> int:
    pseudo_count = generate_pseudo_moves_into(board, side, castling, ep_square, pseudo)
    check_count, checker_square, checker_is_slider, pinned = _legality_context(
        board, side, own_king
    )
    legal_count = 0
    for index in range(pseudo_count):
        move = int(pseudo[index])
        from_square = move_from(move)
        moving_piece = abs(int(board[from_square]))

        # King moves/castles alter the king square; en-passant removes a pawn away from the
        # destination. Keep the exact final-board attack oracle for those geometry-changing cases.
        if moving_piece == KING or (move & FLAG_EP):
            _, _, captured_piece, captured_square = make_move_inplace(
                board, side, castling, ep_square, move
            )
            check_square = move_to(move) if moving_piece == KING else own_king
            legal_move = check_square >= 0 and not is_square_attacked(
                board, check_square, -side
            )
            undo_move_inplace(board, side, move, captured_piece, captured_square)
        else:
            legal_move = _ordinary_legal_with_context(
                move,
                own_king,
                check_count,
                checker_square,
                checker_is_slider,
                pinned,
            )

        if legal_move:
            legal[legal_count] = move
            legal_count += 1
    return legal_count
'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    source = args.path.read_text()
    marker = '@njit(cache=False)\ndef generate_legal_moves_into_with_king(\n'
    if source.count(marker) != 1:
        raise SystemExit(f"legal-generator marker count={source.count(marker)}")
    source = source.replace(marker, HELPERS + marker, 1)

    start = source.index(marker)
    end_marker = '\n\n@njit(cache=False)\ndef generate_legal_moves_into(\n'
    end = source.index(end_marker, start)
    source = source[:start] + REPLACEMENT + source[end:]
    args.path.write_text(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
