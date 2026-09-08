#!/usr/bin/env python3
"""Add exactly one layer of legal quiet checks at qsearch entry.

V13 qsearch searches captures, en-passant and promotions only when not in check. This candidate
keeps that behaviour below qply 0, but at qsearch entry it also retains legal quiet moves that give
an immediate check. The checking move is then followed by the existing checked-qsearch branch,
which searches all legal evasions. Nothing is pruned and evaluation is unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path


OLD = '''    else:
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

NEW = '''    else:
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        if qply == 0:
            # One forcing quiet-check layer at the horizon. Generate exact legal moves once, then
            # retain V13 tacticals plus quiet moves that directly leave the enemy king attacked.
            # After a retained quiet check, recursion enters the existing checked branch and
            # therefore searches every legal evasion. Lower qsearch plies remain V13-identical.
            legal_count = _legal_moves_for_state(
                board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
            )
            if legal_count == 0:
                return 0, False
            enemy_king = int(
                eval_stack[ply][EVAL_BLACK_KING]
                if side == WHITE
                else eval_stack[ply][EVAL_WHITE_KING]
            )
            count = 0
            for legal_index in range(legal_count):
                candidate = int(moves[legal_index])
                keep = _is_tactical(board, candidate)
                if not keep and enemy_king >= 0:
                    child_castling_probe, child_ep_probe, captured_probe, captured_square_probe = make_move_inplace(
                        board, side, castling, ep_square, candidate
                    )
                    keep = is_square_attacked(board, enemy_king, side)
                    undo_move_inplace(
                        board, side, candidate, captured_probe, captured_square_probe
                    )
                if keep:
                    moves[count] = candidate
                    count += 1
            if count == 0:
                return alpha, False
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


def patch(path: Path) -> None:
    source = path.read_text()
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"quiet-check qsearch anchor: expected 1, found {count}")
    source = source.replace(OLD, NEW, 1)
    if source.count("One forcing quiet-check layer") != 1:
        raise SystemExit("quiet-check patch structure drifted")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
