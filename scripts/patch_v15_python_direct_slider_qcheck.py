#!/usr/bin/env python3
"""Add direct quiet slider checks at qsearch root without broad legal generation.

The first root-qcheck candidate proved useful per node but paid ~15% throughput because it built the
complete legal move list and then make/unmade quiet sliders to detect checks. This variant keeps the
same ordinary tactical generator, then appends only legal quiet bishop/rook/queen moves whose moved
slider directly checks the enemy king. It uses the existing king-ray legality context and tests check
geometry without mutating the board. Deeper qsearch remains exact packaged V14.
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
    marker = "_append_direct_quiet_slider_checks"
    if marker in source:
        raise SystemExit("source already contains direct slider qsearch checks")

    old_import = '''    BISHOP,\n    EMPTY,\n    FLAG_CASTLE,\n    FLAG_EP,\n    KING,\n    KNIGHT,\n    MAX_MOVES,\n    PAWN,\n    QUEEN,\n    ROOK,\n    WHITE,\n    generate_legal_moves_into_with_king,\n    generate_legal_tactical_moves_into_with_king,\n    has_any_legal_move_with_king,\n    is_square_attacked,\n    make_move_inplace,\n    move_from,\n    move_promotion,\n    move_to,\n    undo_move_inplace,\n)\n'''
    new_import = '''    BISHOP,\n    BISHOP_DIRS,\n    EMPTY,\n    FLAG_CASTLE,\n    FLAG_EP,\n    KING,\n    KNIGHT,\n    MAX_MOVES,\n    PAWN,\n    QUEEN,\n    ROOK,\n    ROOK_DIRS,\n    WHITE,\n    _inside,\n    _legality_context,\n    _ordinary_legal_with_context,\n    _square,\n    encode_move,\n    generate_legal_moves_into_with_king,\n    generate_legal_tactical_moves_into_with_king,\n    has_any_legal_move_with_king,\n    is_square_attacked,\n    make_move_inplace,\n    move_from,\n    move_promotion,\n    move_to,\n    undo_move_inplace,\n)\n'''
    source = replace_once(source, old_import, new_import, "core imports")

    anchor = '''@njit(cache=False, inline="always")\ndef _search_budget_exhausted(\n'''
    helper = '''@njit(cache=False, inline="always")\ndef _direct_slider_check_after_quiet(\n    board: np.ndarray,\n    from_square: int,\n    to_square: int,\n    piece: int,\n    enemy_king: int,\n) -> bool:\n    """Whether the moved slider itself checks the enemy king after a quiet move."""\n    if enemy_king < 0:\n        return False\n    to_file = to_square & 7\n    to_rank = to_square >> 3\n    king_file = enemy_king & 7\n    king_rank = enemy_king >> 3\n    file_delta = king_file - to_file\n    rank_delta = king_rank - to_rank\n\n    step_file = 0\n    step_rank = 0\n    if (\n        (piece == BISHOP or piece == QUEEN)\n        and abs(file_delta) == abs(rank_delta)\n        and file_delta != 0\n    ):\n        step_file = 1 if file_delta > 0 else -1\n        step_rank = 1 if rank_delta > 0 else -1\n    elif (piece == ROOK or piece == QUEEN) and (file_delta == 0) != (rank_delta == 0):\n        if file_delta != 0:\n            step_file = 1 if file_delta > 0 else -1\n        else:\n            step_rank = 1 if rank_delta > 0 else -1\n    else:\n        return False\n\n    file = to_file + step_file\n    rank = to_rank + step_rank\n    while file != king_file or rank != king_rank:\n        square = _square(file, rank)\n        # The moving slider vacates its source before the check exists.\n        if square != from_square and board[square] != EMPTY:\n            return False\n        file += step_file\n        rank += step_rank\n    return True\n\n\n@njit(cache=False)\ndef _append_direct_quiet_slider_checks(\n    board: np.ndarray,\n    side: int,\n    moves: np.ndarray,\n    count: int,\n    own_king: int,\n    enemy_king: int,\n) -> int:\n    """Append legal direct quiet bishop/rook/queen checks without full legal generation."""\n    check_count, checker_square, checker_is_slider, pinned = _legality_context(\n        board, side, own_king\n    )\n    if check_count != 0:\n        return count\n\n    for from_square in range(64):\n        signed_piece = int(board[from_square])\n        if signed_piece * side <= 0:\n            continue\n        piece = signed_piece * side\n        if piece != BISHOP and piece != ROOK and piece != QUEEN:\n            continue\n        file = from_square & 7\n        rank = from_square >> 3\n\n        for family in range(2):\n            if piece == BISHOP and family == 1:\n                continue\n            if piece == ROOK and family == 0:\n                continue\n            directions = BISHOP_DIRS if family == 0 else ROOK_DIRS\n            for delta_file, delta_rank in directions:\n                target_file = file + delta_file\n                target_rank = rank + delta_rank\n                while _inside(target_file, target_rank):\n                    target = _square(target_file, target_rank)\n                    if board[target] != EMPTY:\n                        break\n                    if _direct_slider_check_after_quiet(\n                        board, from_square, target, piece, enemy_king\n                    ):\n                        move = encode_move(from_square, target)\n                        if _ordinary_legal_with_context(\n                            move,\n                            own_king,\n                            check_count,\n                            checker_square,\n                            checker_is_slider,\n                            pinned,\n                        ):\n                            if count < MAX_MOVES:\n                                moves[count] = move\n                                count += 1\n                    target_file += delta_file\n                    target_rank += delta_rank\n    return count\n\n\n@njit(cache=False, inline="always")\ndef _search_budget_exhausted(\n'''
    source = replace_once(source, anchor, helper, "helper insertion")

    old_qsearch = '''        count = generate_legal_tactical_moves_into_with_king(\n            board, side, ep_square, pseudo, moves, own_king\n        )\n        if count == 0:\n            if has_any_legal_move_with_king(\n                board, side, castling, ep_square, pseudo, own_king\n            ):\n                return alpha, False\n            return 0, False\n        _order_moves(board, moves, count, -1, score_stack[ply])\n'''
    new_qsearch = '''        count = generate_legal_tactical_moves_into_with_king(\n            board, side, ep_square, pseudo, moves, own_king\n        )\n        if qply == 0:\n            enemy_king = int(\n                eval_stack[ply][EVAL_BLACK_KING]\n                if side == WHITE\n                else eval_stack[ply][EVAL_WHITE_KING]\n            )\n            count = _append_direct_quiet_slider_checks(\n                board, side, moves, count, own_king, enemy_king\n            )\n        if count == 0:\n            if has_any_legal_move_with_king(\n                board, side, castling, ep_square, pseudo, own_king\n            ):\n                return alpha, False\n            return 0, False\n        _order_moves(board, moves, count, -1, score_stack[ply])\n'''
    source = replace_once(source, old_qsearch, new_qsearch, "qsearch non-check generation")

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
