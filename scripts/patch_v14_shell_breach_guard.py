#!/usr/bin/env python3
"""Add a narrowly-scoped root penalty for king-shield pawn moves that enable quiet slider checks.

The guard is deliberately not a general king-danger evaluator. It activates only when:
  * the root move is a quiet pawn move,
  * the pawn starts on a square adjacent to our king,
  * after the move, the opponent has at least one legal quiet bishop/rook/queen check.

Such moves receive a fixed 100cp root penalty. No interior-node evaluation, pruning, qsearch, move
membership, legality, TT semantics or learned evaluation is changed.
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
    if "_root_shell_breach_probe" in source:
        raise SystemExit("shell-breach guard already applied")

    anchor = '''@njit(cache=False)
def _root(
'''
    helper = '''@njit(cache=False, inline="always")
def _is_adjacent_king_shield_pawn_push(
    board: np.ndarray,
    side: int,
    move: int,
    own_king: int,
) -> bool:
    from_square = move_from(move)
    to_square = move_to(move)
    if int(board[from_square]) != side * PAWN:
        return False
    if int(board[to_square]) != EMPTY:
        return False
    if move & FLAG_EP or move_promotion(move) != 0:
        return False
    from_file = from_square & 7
    from_rank = from_square >> 3
    king_file = own_king & 7
    king_rank = own_king >> 3
    return abs(from_file - king_file) <= 1 and abs(from_rank - king_rank) <= 1


@njit(cache=False)
def _opponent_has_quiet_slider_check(
    board: np.ndarray,
    opponent: int,
    castling: int,
    ep_square: int,
    own_king: int,
    pseudo: np.ndarray,
    moves: np.ndarray,
    eval_state: np.ndarray,
) -> bool:
    count = _legal_moves_for_state(
        board, opponent, castling, ep_square, pseudo, moves, eval_state
    )
    for index in range(count):
        move = int(moves[index])
        from_square = move_from(move)
        to_square = move_to(move)
        piece = abs(int(board[from_square]))
        if piece != BISHOP and piece != ROOK and piece != QUEEN:
            continue
        if int(board[to_square]) != EMPTY:
            continue
        if move_promotion(move) != 0:
            continue
        _, _, captured_piece, captured_square = make_move_inplace(
            board, opponent, castling, ep_square, move
        )
        gives_check = is_square_attacked(board, own_king, opponent)
        undo_move_inplace(board, opponent, move, captured_piece, captured_square)
        if gives_check:
            return True
    return False


@njit(cache=False, inline="always")
def _root_shell_breach_probe(
    board: np.ndarray,
    side: int,
    move: int,
    own_king: int,
) -> bool:
    return _is_adjacent_king_shield_pawn_push(board, side, move, own_king)


@njit(cache=False)
def _root(
'''
    source = replace_once(source, anchor, helper, "root helper insertion")

    root_start = source.index('@njit(cache=False)\ndef _root(')
    try:
        root_end = source.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(', root_start)
    except ValueError:
        root_end = source.index('\n\n@njit(cache=False)\ndef iterative_search_stateful_timed', root_start)
    root = source[root_start:root_end]

    old_probe = '''        move = int(moves[index])
        child_depth = depth - 1
'''
    new_probe = '''        move = int(moves[index])
        own_king_before = int(
            eval_stack[0][EVAL_WHITE_KING] if side == WHITE else eval_stack[0][EVAL_BLACK_KING]
        )
        shell_breach_probe = _root_shell_breach_probe(
            board, side, move, own_king_before
        )
        child_depth = depth - 1
'''
    root = replace_once(root, old_probe, new_probe, "root probe setup")

    old_make = '''        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[1] = _child_position_key(
'''
    new_make = '''        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        shell_breach = False
        if shell_breach_probe:
            shell_breach = _opponent_has_quiet_slider_check(
                board,
                -side,
                child_castling,
                child_ep,
                own_king_before,
                pseudo_stack[1],
                move_stack[1],
                eval_stack[1],
            )
        path_keys[1] = _child_position_key(
'''
    root = replace_once(root, old_make, new_make, "root shell check")

    old_score = '''        score = -score
        if score > best_score:
'''
    new_score = '''        score = -score
        if shell_breach:
            score -= 100
        if score > best_score:
'''
    root = replace_once(root, old_score, new_score, "root score penalty")

    source = source[:root_start] + root + source[root_end:]
    if source.count("shell_breach") < 5:
        raise SystemExit("shell-breach patch structure drifted")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
