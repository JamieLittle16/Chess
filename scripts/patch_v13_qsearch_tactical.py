from __future__ import annotations

import argparse
from pathlib import Path

TACTICAL_PSEUDO = r'''

@njit(cache=False)
def generate_pseudo_tactical_moves_into(
    board: np.ndarray,
    side: int,
    ep_square: int,
    moves: np.ndarray,
) -> int:
    """Generate captures, en-passant and promotions in normal pseudo-move order."""
    count = 0
    for from_square in range(64):
        signed_piece = int(board[from_square])
        if signed_piece * side <= 0:
            continue
        piece = signed_piece * side
        file = from_square & 7
        rank = from_square >> 3

        if piece == PAWN:
            next_rank = rank + side
            if 0 <= next_rank < 8:
                one_step = _square(file, next_rank)
                if next_rank == (7 if side == WHITE else 0) and board[one_step] == EMPTY:
                    count = _append_pawn_target(moves, count, from_square, one_step, True, 0)
                for delta_file in (-1, 1):
                    target_file = file + delta_file
                    if not 0 <= target_file < 8:
                        continue
                    target = _square(target_file, next_rank)
                    target_piece = int(board[target])
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append_pawn_target(
                            moves,
                            count,
                            from_square,
                            target,
                            next_rank == (7 if side == WHITE else 0),
                            0,
                        )
                    elif target == ep_square and target_piece == EMPTY:
                        count = _append(
                            moves, count, encode_move(from_square, target, 0, FLAG_EP)
                        )
            continue

        if piece == KNIGHT:
            for index in range(int(KNIGHT_TARGET_COUNTS[from_square])):
                target = int(KNIGHT_TARGETS[from_square, index])
                target_piece = int(board[target])
                if target_piece * side < 0 and abs(target_piece) != KING:
                    count = _append(moves, count, encode_move(from_square, target))
            continue

        if piece == KING:
            for index in range(int(KING_TARGET_COUNTS[from_square])):
                target = int(KING_TARGETS[from_square, index])
                target_piece = int(board[target])
                if target_piece * side < 0 and abs(target_piece) != KING:
                    count = _append(moves, count, encode_move(from_square, target))
            continue

        directions = BISHOP_DIRS if piece == BISHOP else ROOK_DIRS
        if piece == QUEEN:
            for delta_file, delta_rank in BISHOP_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while _inside(target_file, target_rank):
                    target = _square(target_file, target_rank)
                    target_piece = int(board[target])
                    if target_piece != EMPTY:
                        if target_piece * side < 0 and abs(target_piece) != KING:
                            count = _append(moves, count, encode_move(from_square, target))
                        break
                    target_file += delta_file
                    target_rank += delta_rank
            directions = ROOK_DIRS

        for delta_file, delta_rank in directions:
            target_file = file + delta_file
            target_rank = rank + delta_rank
            while _inside(target_file, target_rank):
                target = _square(target_file, target_rank)
                target_piece = int(board[target])
                if target_piece != EMPTY:
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append(moves, count, encode_move(from_square, target))
                    break
                target_file += delta_file
                target_rank += delta_rank
    return count
'''

TACTICAL_LEGAL = r'''

@njit(cache=False)
def generate_legal_tactical_moves_into_with_king(
    board: np.ndarray,
    side: int,
    ep_square: int,
    pseudo: np.ndarray,
    legal: np.ndarray,
    own_king: int,
) -> int:
    pseudo_count = generate_pseudo_tactical_moves_into(board, side, ep_square, pseudo)
    check_count, checker_square, checker_is_slider, pinned = _legality_context(
        board, side, own_king
    )
    legal_count = 0
    for index in range(pseudo_count):
        move = int(pseudo[index])
        from_square = move_from(move)
        moving_piece = abs(int(board[from_square]))
        if moving_piece == KING or (move & FLAG_EP):
            _, _, captured_piece, captured_square = make_move_inplace(
                board, side, 0, ep_square, move
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


@njit(cache=False)
def has_any_legal_move_with_king(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    pseudo: np.ndarray,
    own_king: int,
) -> bool:
    """Exact early-exit legal-move existence test for stalemate handling."""
    pseudo_count = generate_pseudo_moves_into(board, side, castling, ep_square, pseudo)
    check_count, checker_square, checker_is_slider, pinned = _legality_context(
        board, side, own_king
    )
    for index in range(pseudo_count):
        move = int(pseudo[index])
        from_square = move_from(move)
        moving_piece = abs(int(board[from_square]))
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
            return True
    return False
'''

OLD_QSEARCH = '''    pseudo = pseudo_stack[ply]\n    moves = move_stack[ply]\n    count = _legal_moves_for_state(\n        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]\n    )\n    if count == 0:\n        return (-MATE + ply if checked else 0), False\n    if checked:\n        _order_moves(board, moves, count, -1, score_stack[ply])\n    else:\n        count = _order_tactical_moves(board, moves, count, -1, score_stack[ply])\n        if count == 0:\n            return alpha, False\n'''

NEW_QSEARCH = '''    pseudo = pseudo_stack[ply]\n    moves = move_stack[ply]\n    if checked:\n        count = _legal_moves_for_state(\n            board, side, castling, ep_square, pseudo, moves, eval_stack[ply]\n        )\n        if count == 0:\n            return -MATE + ply, False\n        _order_moves(board, moves, count, -1, score_stack[ply])\n    else:\n        own_king = int(\n            eval_stack[ply][EVAL_WHITE_KING]\n            if side == WHITE\n            else eval_stack[ply][EVAL_BLACK_KING]\n        )\n        count = generate_legal_tactical_moves_into_with_king(\n            board, side, ep_square, pseudo, moves, own_king\n        )\n        if count == 0:\n            if has_any_legal_move_with_king(\n                board, side, castling, ep_square, pseudo, own_king\n            ):\n                return alpha, False\n            return 0, False\n        _order_moves(board, moves, count, -1, score_stack[ply])\n'''


def patch(core_path: Path, search_path: Path) -> None:
    core = core_path.read_text()
    pseudo_marker = "\n\n@njit(cache=False)\ndef generate_pseudo_moves(\n"
    legal_marker = "\n\n@njit(cache=False)\ndef generate_legal_moves_into(\n"
    assert "def generate_pseudo_tactical_moves_into(" not in core
    assert "def generate_legal_tactical_moves_into_with_king(" not in core
    assert core.count(pseudo_marker) == 1, core.count(pseudo_marker)
    assert core.count(legal_marker) == 1, core.count(legal_marker)
    core = core.replace(pseudo_marker, TACTICAL_PSEUDO + pseudo_marker, 1)
    core = core.replace(legal_marker, TACTICAL_LEGAL + legal_marker, 1)
    core_path.write_text(core)

    search = search_path.read_text()
    import_marker = "    generate_legal_moves_into_with_king,\n"
    assert search.count(import_marker) == 1, search.count(import_marker)
    search = search.replace(
        import_marker,
        import_marker
        + "    generate_legal_tactical_moves_into_with_king,\n"
        + "    has_any_legal_move_with_king,\n",
        1,
    )
    assert search.count(OLD_QSEARCH) == 1, search.count(OLD_QSEARCH)
    search = search.replace(OLD_QSEARCH, NEW_QSEARCH, 1)
    search_path.write_text(search)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("core", type=Path)
    parser.add_argument("search", type=Path)
    args = parser.parse_args()
    patch(args.core, args.search)


if __name__ == "__main__":
    main()
