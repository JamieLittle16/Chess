#!/usr/bin/env python3
"""Patch exact V13 with a faster qply-0 quiet-slider-check generator.

This preserves V14 qcheck A's bounded search semantics: ordinary V13 tacticals plus legal quiet
bishop/rook/queen checks are searched only at qply == 0. Unlike A, it does not generate every legal
quiet move first. It starts from V13's direct tactical generator and scans only empty slider rays,
using the qualified legality context and the exact make/attack/unmake oracle for check detection.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()
    marker = "_append_root_qsearch_quiet_slider_checks_fast"
    if marker in source:
        raise SystemExit("source already contains fast root-qsearch checks")

    old_import = """    WHITE,
    generate_legal_moves_into_with_king,
    generate_legal_tactical_moves_into_with_king,
"""
    new_import = """    WHITE,
    BISHOP_DIRS,
    ROOK_DIRS,
    _legality_context,
    _ordinary_legal_with_context,
    encode_move,
    generate_legal_moves_into_with_king,
    generate_legal_tactical_moves_into_with_king,
"""
    source = replace_once(source, old_import, new_import, "core imports")

    anchor = '''@njit(cache=False, inline="always")
def _search_budget_exhausted(
'''
    helper = '''@njit(cache=False)
def _append_root_qsearch_quiet_slider_checks_fast(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    moves: np.ndarray,
    count: int,
    own_king: int,
    opponent_king: int,
) -> int:
    """Append legal quiet B/R/Q checks without generating unrelated quiet moves."""
    check_count, checker_square, checker_is_slider, pinned = _legality_context(
        board, side, own_king
    )
    # Called only from the non-check qsearch branch, but retain exactness if that contract drifts.
    if check_count != 0:
        return count

    for from_square in range(64):
        signed_piece = int(board[from_square])
        if signed_piece * side <= 0:
            continue
        piece = abs(signed_piece)
        if piece != BISHOP and piece != ROOK and piece != QUEEN:
            continue

        from_file = from_square & 7
        from_rank = from_square >> 3
        for family in range(2):
            if piece == BISHOP and family == 1:
                continue
            if piece == ROOK and family == 0:
                continue
            directions = BISHOP_DIRS if family == 0 else ROOK_DIRS
            for direction_index in range(4):
                delta_file = int(directions[direction_index][0])
                delta_rank = int(directions[direction_index][1])
                target_file = from_file + delta_file
                target_rank = from_rank + delta_rank
                while 0 <= target_file < 8 and 0 <= target_rank < 8:
                    target = target_rank * 8 + target_file
                    target_piece = int(board[target])
                    if target_piece != EMPTY:
                        break

                    move = encode_move(from_square, target)
                    if _ordinary_legal_with_context(
                        move,
                        own_king,
                        check_count,
                        checker_square,
                        checker_is_slider,
                        pinned,
                    ):
                        _, _, captured_piece, captured_square = make_move_inplace(
                            board, side, castling, ep_square, move
                        )
                        gives_check = opponent_king >= 0 and is_square_attacked(
                            board, opponent_king, side
                        )
                        undo_move_inplace(
                            board, side, move, captured_piece, captured_square
                        )
                        if gives_check:
                            moves[count] = move
                            count += 1
                    target_file += delta_file
                    target_rank += delta_rank
    return count


@njit(cache=False, inline="always")
def _search_budget_exhausted(
'''
    source = replace_once(source, anchor, helper, "helper insertion")

    old = '''    else:
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        count = generate_legal_tactical_moves_into_with_king(
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
    new = '''    else:
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        count = generate_legal_tactical_moves_into_with_king(
            board, side, ep_square, pseudo, moves, own_king
        )
        if qply == 0:
            opponent_king = int(
                eval_stack[ply][EVAL_BLACK_KING]
                if side == WHITE
                else eval_stack[ply][EVAL_WHITE_KING]
            )
            count = _append_root_qsearch_quiet_slider_checks_fast(
                board,
                side,
                castling,
                ep_square,
                moves,
                count,
                own_king,
                opponent_king,
            )
        if count == 0:
            if has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                return alpha, False
            return 0, False
        _order_moves(board, moves, count, -1, score_stack[ply])
'''
    source = replace_once(source, old, new, "qsearch non-check move generation")

    if source.count(marker) != 2:
        raise SystemExit(f"unexpected helper use count: {source.count(marker)}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
