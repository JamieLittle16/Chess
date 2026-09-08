#!/usr/bin/env python3
"""Append legal quiet *direct* slider checks to qply-0 without full legal generation.

The first V15 Python root-qcheck experiment proved useful chess signal (+25 Elo at equal nodes) but
paid ~15% NPS because it generated every legal move and then filtered. This variant keeps V14's
existing tactical generator and scans only empty bishop/rook/queen destinations that can directly
check the enemy king. Ordinary pin/check legality is reused from numba_core; no make/unmake is
needed for the quiet-check test.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


CORE_HELPER = r'''

@njit(cache=False, inline="always")
def _quiet_slider_direct_check(
    board: np.ndarray,
    piece: int,
    from_square: int,
    target: int,
    opponent_king: int,
) -> bool:
    if opponent_king < 0:
        return False

    target_file = target & 7
    target_rank = target >> 3
    king_file = opponent_king & 7
    king_rank = opponent_king >> 3
    delta_file = king_file - target_file
    delta_rank = king_rank - target_rank

    if piece == BISHOP:
        if delta_file == 0 or abs(delta_file) != abs(delta_rank):
            return False
    elif piece == ROOK:
        if delta_file != 0 and delta_rank != 0:
            return False
    else:  # QUEEN
        if not (
            delta_file == 0
            or delta_rank == 0
            or (delta_file != 0 and abs(delta_file) == abs(delta_rank))
        ):
            return False

    step_file = 0 if delta_file == 0 else (1 if delta_file > 0 else -1)
    step_rank = 0 if delta_rank == 0 else (1 if delta_rank > 0 else -1)
    file = target_file + step_file
    rank = target_rank + step_rank
    while file != king_file or rank != king_rank:
        square = _square(file, rank)
        # The moving slider vacates from_square, so ignore that single current-board blocker.
        if square != from_square and board[square] != EMPTY:
            return False
        file += step_file
        rank += step_rank
    return True


@njit(cache=False)
def append_legal_quiet_slider_checks_into(
    board: np.ndarray,
    side: int,
    legal: np.ndarray,
    legal_count: int,
    own_king: int,
    opponent_king: int,
) -> int:
    """Append legal empty-square B/R/Q moves that give direct check."""
    check_count, checker_square, checker_is_slider, pinned = _legality_context(
        board, side, own_king
    )
    # This helper is only used from the non-check qsearch branch. Be conservative if that invariant
    # is ever violated by later refactors.
    if check_count != 0:
        return legal_count

    for from_square in range(64):
        signed_piece = int(board[from_square])
        if signed_piece * side <= 0:
            continue
        piece = signed_piece * side
        if piece != BISHOP and piece != ROOK and piece != QUEEN:
            continue
        file = from_square & 7
        rank = from_square >> 3

        directions = BISHOP_DIRS if piece == BISHOP else ROOK_DIRS
        if piece == QUEEN:
            for delta_file, delta_rank in BISHOP_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while _inside(target_file, target_rank):
                    target = _square(target_file, target_rank)
                    if board[target] != EMPTY:
                        break
                    move = encode_move(from_square, target)
                    if _quiet_slider_direct_check(
                        board, piece, from_square, target, opponent_king
                    ) and _ordinary_legal_with_context(
                        move,
                        own_king,
                        check_count,
                        checker_square,
                        checker_is_slider,
                        pinned,
                    ):
                        legal[legal_count] = move
                        legal_count += 1
                    target_file += delta_file
                    target_rank += delta_rank
            directions = ROOK_DIRS

        for delta_file, delta_rank in directions:
            target_file = file + delta_file
            target_rank = rank + delta_rank
            while _inside(target_file, target_rank):
                target = _square(target_file, target_rank)
                if board[target] != EMPTY:
                    break
                move = encode_move(from_square, target)
                if _quiet_slider_direct_check(
                    board, piece, from_square, target, opponent_king
                ) and _ordinary_legal_with_context(
                    move,
                    own_king,
                    check_count,
                    checker_square,
                    checker_is_slider,
                    pinned,
                ):
                    legal[legal_count] = move
                    legal_count += 1
                target_file += delta_file
                target_rank += delta_rank
    return legal_count
'''


def patch(core_path: Path, search_path: Path) -> None:
    core = core_path.read_text()
    marker = "def append_legal_quiet_slider_checks_into("
    if marker in core:
        raise SystemExit("core already contains fast direct-check helper")
    anchor = "\n\n@njit(cache=False)\ndef generate_legal_tactical_moves_into_with_king(\n"
    core = replace_once(core, anchor, CORE_HELPER + anchor, "core helper insertion")
    core_path.write_text(core)

    search = search_path.read_text()
    import_anchor = "    generate_legal_tactical_moves_into_with_king,\n"
    search = replace_once(
        search,
        import_anchor,
        import_anchor + "    append_legal_quiet_slider_checks_into,\n",
        "search import",
    )

    old = '''        count = generate_legal_tactical_moves_into_with_king(
            board, side, ep_square, pseudo, moves, own_king
        )
        if count == 0:
            if has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                return alpha, False
            return 0, False
        _order_moves(board, moves, count, -1, score_stack[ply])
'''
    new = '''        count = generate_legal_tactical_moves_into_with_king(
            board, side, ep_square, pseudo, moves, own_king
        )
        if qply == 0:
            opponent_king = int(
                eval_stack[ply][EVAL_BLACK_KING]
                if side == WHITE
                else eval_stack[ply][EVAL_WHITE_KING]
            )
            count = append_legal_quiet_slider_checks_into(
                board, side, moves, count, own_king, opponent_king
            )
        if count == 0:
            if has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                return alpha, False
            return 0, False
        _order_moves(board, moves, count, -1, score_stack[ply])
'''
    search = replace_once(search, old, new, "qsearch root direct checks")
    if search.count("append_legal_quiet_slider_checks_into") != 2:
        raise SystemExit("unexpected fast direct-check helper reference count")
    search_path.write_text(search)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("core", type=Path)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    patch(args.core, args.search)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
