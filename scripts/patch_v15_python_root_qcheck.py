#!/usr/bin/env python3
"""Add quiet slider checks only at the first qsearch ply.

This is a deliberately bounded threat-awareness experiment for the packaged Python V14 engine.
Ordinary qsearch searches legal captures, en-passant and promotions. At qply == 0 this patch uses
one full legal generation and retains those ordinary tacticals plus quiet bishop/rook/queen moves
that give immediate check. Deeper qsearch plies remain exactly V14-like, so the extension cannot
recursively explode the tree.
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
    marker = "_retain_root_qsearch_slider_checks"
    if marker in source:
        raise SystemExit("source already contains root-qsearch quiet checks")

    anchor = '''@njit(cache=False, inline="always")
def _search_budget_exhausted(
'''
    helper = '''@njit(cache=False)
def _retain_root_qsearch_slider_checks(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    pseudo: np.ndarray,
    moves: np.ndarray,
    own_king: int,
    opponent_king: int,
) -> tuple[int, int]:
    """Return (retained_count, legal_count) for qply-0 tactical + quiet slider checks."""
    legal_count = generate_legal_moves_into_with_king(
        board, side, castling, ep_square, pseudo, moves, own_king
    )
    retained = 0
    for index in range(legal_count):
        move = int(moves[index])
        if _is_tactical(board, move):
            moves[retained] = move
            retained += 1
            continue

        from_square = move_from(move)
        piece = abs(int(board[from_square]))
        if piece != BISHOP and piece != ROOK and piece != QUEEN:
            continue

        _, _, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        gives_check = opponent_king >= 0 and is_square_attacked(
            board, opponent_king, side
        )
        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if gives_check:
            moves[retained] = move
            retained += 1

    return retained, legal_count


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
        if qply == 0:
            opponent_king = int(
                eval_stack[ply][EVAL_BLACK_KING]
                if side == WHITE
                else eval_stack[ply][EVAL_WHITE_KING]
            )
            count, legal_count = _retain_root_qsearch_slider_checks(
                board,
                side,
                castling,
                ep_square,
                pseudo,
                moves,
                own_king,
                opponent_king,
            )
            if count == 0:
                return (0 if legal_count == 0 else alpha), False
        else:
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
