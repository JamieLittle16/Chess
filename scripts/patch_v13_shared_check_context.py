from __future__ import annotations

import argparse
from pathlib import Path

OLD_CORE = '''@njit(cache=False)\ndef generate_legal_moves_into_with_king(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    ep_square: int,\n    pseudo: np.ndarray,\n    legal: np.ndarray,\n    own_king: int,\n) -> int:\n    pseudo_count = generate_pseudo_moves_into(board, side, castling, ep_square, pseudo)\n    check_count, checker_square, checker_is_slider, pinned = _legality_context(\n        board, side, own_king\n    )\n    legal_count = 0\n    for index in range(pseudo_count):\n        move = int(pseudo[index])\n        from_square = move_from(move)\n        moving_piece = abs(int(board[from_square]))\n\n        # King moves/castles alter the king square; en-passant removes a pawn away from the\n        # destination. Keep the exact final-board attack oracle for those geometry-changing cases.\n        if moving_piece == KING or (move & FLAG_EP):\n            _, _, captured_piece, captured_square = make_move_inplace(\n                board, side, castling, ep_square, move\n            )\n            check_square = move_to(move) if moving_piece == KING else own_king\n            legal_move = check_square >= 0 and not is_square_attacked(\n                board, check_square, -side\n            )\n            undo_move_inplace(board, side, move, captured_piece, captured_square)\n        else:\n            legal_move = _ordinary_legal_with_context(\n                move,\n                own_king,\n                check_count,\n                checker_square,\n                checker_is_slider,\n                pinned,\n            )\n\n        if legal_move:\n            legal[legal_count] = move\n            legal_count += 1\n    return legal_count\n'''

NEW_CORE = '''@njit(cache=False)\ndef generate_legal_moves_into_with_king_and_check(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    ep_square: int,\n    pseudo: np.ndarray,\n    legal: np.ndarray,\n    own_king: int,\n) -> tuple[int, bool]:\n    \"\"\"Generate legal moves and expose the already-computed node check state.\"\"\"\n    pseudo_count = generate_pseudo_moves_into(board, side, castling, ep_square, pseudo)\n    check_count, checker_square, checker_is_slider, pinned = _legality_context(\n        board, side, own_king\n    )\n    legal_count = 0\n    for index in range(pseudo_count):\n        move = int(pseudo[index])\n        from_square = move_from(move)\n        moving_piece = abs(int(board[from_square]))\n\n        # King moves/castles alter the king square; en-passant removes a pawn away from the\n        # destination. Keep the exact final-board attack oracle for those geometry-changing cases.\n        if moving_piece == KING or (move & FLAG_EP):\n            _, _, captured_piece, captured_square = make_move_inplace(\n                board, side, castling, ep_square, move\n            )\n            check_square = move_to(move) if moving_piece == KING else own_king\n            legal_move = check_square >= 0 and not is_square_attacked(\n                board, check_square, -side\n            )\n            undo_move_inplace(board, side, move, captured_piece, captured_square)\n        else:\n            legal_move = _ordinary_legal_with_context(\n                move,\n                own_king,\n                check_count,\n                checker_square,\n                checker_is_slider,\n                pinned,\n            )\n\n        if legal_move:\n            legal[legal_count] = move\n            legal_count += 1\n    return legal_count, check_count > 0\n\n\n@njit(cache=False)\ndef generate_legal_moves_into_with_king(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    ep_square: int,\n    pseudo: np.ndarray,\n    legal: np.ndarray,\n    own_king: int,\n) -> int:\n    legal_count, _ = generate_legal_moves_into_with_king_and_check(\n        board, side, castling, ep_square, pseudo, legal, own_king\n    )\n    return legal_count\n'''

OLD_HELPER = '''@njit(cache=False, inline="always")\ndef _legal_moves_for_state(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    ep_square: int,\n    pseudo: np.ndarray,\n    moves: np.ndarray,\n    state: np.ndarray,\n) -> int:\n    king = int(state[EVAL_WHITE_KING] if side == WHITE else state[EVAL_BLACK_KING])\n    return generate_legal_moves_into_with_king(\n        board, side, castling, ep_square, pseudo, moves, king\n    )\n'''

NEW_HELPER = OLD_HELPER + '''\n\n@njit(cache=False, inline="always")\ndef _legal_moves_for_state_and_check(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    ep_square: int,\n    pseudo: np.ndarray,\n    moves: np.ndarray,\n    state: np.ndarray,\n) -> tuple[int, bool]:\n    king = int(state[EVAL_WHITE_KING] if side == WHITE else state[EVAL_BLACK_KING])\n    return generate_legal_moves_into_with_king_and_check(\n        board, side, castling, ep_square, pseudo, moves, king\n    )\n'''

OLD_NEGAMAX = '''    count = _legal_moves_for_state(\n        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]\n    )\n    if count == 0:\n        return (-MATE + ply if _state_in_check(board, side, eval_stack[ply]) else 0), False\n\n    checked = _state_in_check(board, side, eval_stack[ply])\n'''

NEW_NEGAMAX = '''    count, checked = _legal_moves_for_state_and_check(\n        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]\n    )\n    if count == 0:\n        return (-MATE + ply if checked else 0), False\n'''


def patch(core_path: Path, search_path: Path) -> None:
    core = core_path.read_text()
    assert core.count(OLD_CORE) == 1, core.count(OLD_CORE)
    core = core.replace(OLD_CORE, NEW_CORE, 1)
    core_path.write_text(core)

    search = search_path.read_text()
    marker = '    generate_legal_moves_into_with_king,\n'
    assert search.count(marker) == 1, search.count(marker)
    search = search.replace(
        marker,
        marker + '    generate_legal_moves_into_with_king_and_check,\n',
        1,
    )
    assert search.count(OLD_HELPER) == 1, search.count(OLD_HELPER)
    search = search.replace(OLD_HELPER, NEW_HELPER, 1)
    assert search.count(OLD_NEGAMAX) == 1, search.count(OLD_NEGAMAX)
    search = search.replace(OLD_NEGAMAX, NEW_NEGAMAX, 1)
    search_path.write_text(search)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('core', type=Path)
    parser.add_argument('search', type=Path)
    args = parser.parse_args()
    patch(args.core, args.search)


if __name__ == '__main__':
    main()
