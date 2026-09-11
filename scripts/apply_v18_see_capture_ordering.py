#!/usr/bin/env python3
"""Add static exchange evaluation to capture ordering only; never prune a legal move."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    def rep(old: str, new: str, count: int = 1) -> None:
        nonlocal s
        actual = s.count(old)
        if actual != count:
            raise RuntimeError(f"anchor count {actual} != {count}: {old[:100]!r}")
        s = s.replace(old, new, count)

    rep("    BISHOP,\n", "    BISHOP,\n    BISHOP_DIRS,\n")
    rep(
        "    KING,\n    KNIGHT,\n    MAX_MOVES,\n",
        "    KING,\n    KING_TARGET_COUNTS,\n    KING_TARGETS,\n    KNIGHT,\n    KNIGHT_TARGET_COUNTS,\n    KNIGHT_TARGETS,\n    MAX_MOVES,\n",
    )
    rep("    QUEEN,\n    ROOK,\n    WHITE,\n", "    QUEEN,\n    ROOK,\n    ROOK_DIRS,\n    WHITE,\n")

    anchor = "@njit(cache=False)\ndef _move_order_score(board: np.ndarray, move: int, preferred: int) -> int:\n"
    helpers = r'''@njit(cache=False)
def _see_least_attacker(board: np.ndarray, target: int, side: int) -> tuple[int, int]:
    """Return the least-valued pseudo-legal attacker of target for ordering-only SEE."""
    target_file = target & 7
    target_rank = target >> 3

    source_rank = target_rank - side
    if 0 <= source_rank < 8:
        for delta_file in (-1, 1):
            source_file = target_file - delta_file
            if 0 <= source_file < 8:
                source = source_rank * 8 + source_file
                if int(board[source]) == side * PAWN:
                    return source, PAWN

    for index in range(int(KNIGHT_TARGET_COUNTS[target])):
        source = int(KNIGHT_TARGETS[target, index])
        if int(board[source]) == side * KNIGHT:
            return source, KNIGHT

    queen_source = -1
    for delta_file, delta_rank in BISHOP_DIRS:
        source_file = target_file + delta_file
        source_rank = target_rank + delta_rank
        while 0 <= source_file < 8 and 0 <= source_rank < 8:
            source = source_rank * 8 + source_file
            signed_piece = int(board[source])
            if signed_piece != EMPTY:
                if signed_piece == side * BISHOP:
                    return source, BISHOP
                if signed_piece == side * QUEEN and queen_source < 0:
                    queen_source = source
                break
            source_file += delta_file
            source_rank += delta_rank

    for delta_file, delta_rank in ROOK_DIRS:
        source_file = target_file + delta_file
        source_rank = target_rank + delta_rank
        while 0 <= source_file < 8 and 0 <= source_rank < 8:
            source = source_rank * 8 + source_file
            signed_piece = int(board[source])
            if signed_piece != EMPTY:
                if signed_piece == side * ROOK:
                    return source, ROOK
                if signed_piece == side * QUEEN and queen_source < 0:
                    queen_source = source
                break
            source_file += delta_file
            source_rank += delta_rank

    if queen_source >= 0:
        return queen_source, QUEEN

    for index in range(int(KING_TARGET_COUNTS[target])):
        source = int(KING_TARGETS[target, index])
        if int(board[source]) == side * KING:
            return source, KING
    return -1, EMPTY


@njit(cache=False)
def _see_capture_ordering(board: np.ndarray, move: int) -> int:
    """Swap-off estimate used only to rank captures. It never removes a move."""
    from_square = move_from(move)
    to_square = move_to(move)
    signed_attacker = int(board[from_square])
    side = 1 if signed_attacker > 0 else -1
    attacker = abs(signed_attacker)
    promotion = move_promotion(move)
    ep = bool(move & FLAG_EP)
    captured_square = to_square - side * 8 if ep else to_square
    captured_signed = int(board[captured_square])
    captured = PAWN if ep else abs(captured_signed)
    if captured == EMPTY:
        return 0

    gains = np.empty(32, dtype=np.int32)
    sources = np.empty(31, dtype=np.int32)
    source_pieces = np.empty(31, dtype=np.int32)
    old_targets = np.empty(31, dtype=np.int32)
    promotion_gain = int(PIECE_VALUE[promotion]) - int(PIECE_VALUE[PAWN]) if promotion else 0
    gains[0] = int(PIECE_VALUE[captured]) + promotion_gain

    original_to = int(board[to_square])
    board[from_square] = EMPTY
    if ep:
        board[captured_square] = EMPTY
    board[to_square] = side * (promotion if promotion else attacker)

    depth = 0
    recapture_side = -side
    while depth < 31:
        source, piece = _see_least_attacker(board, to_square, recapture_side)
        if source < 0:
            break
        old_target = int(board[to_square])
        moving_signed = int(board[source])
        promoted_piece = piece
        target_rank = to_square >> 3
        if piece == PAWN and (target_rank == 0 or target_rank == 7):
            promoted_piece = QUEEN

        board[source] = EMPTY
        board[to_square] = recapture_side * promoted_piece
        if piece == KING and is_square_attacked(board, to_square, -recapture_side):
            board[source] = moving_signed
            board[to_square] = old_target
            break

        sources[depth] = source
        source_pieces[depth] = moving_signed
        old_targets[depth] = old_target
        depth += 1
        gains[depth] = int(PIECE_VALUE[abs(old_target)]) - gains[depth - 1]
        recapture_side = -recapture_side

    for restore_index in range(depth - 1, -1, -1):
        board[int(sources[restore_index])] = int(source_pieces[restore_index])
        board[to_square] = int(old_targets[restore_index])
    board[from_square] = signed_attacker
    if ep:
        board[to_square] = original_to
        board[captured_square] = captured_signed
    else:
        board[to_square] = original_to

    for back in range(depth, 0, -1):
        gains[back - 1] = -max(-gains[back - 1], gains[back])
    return int(gains[0])


'''
    rep(anchor, helpers + anchor)

    old = "    if target:\n        score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"
    new = "    if target:\n        see = int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n        if int(PIECE_VALUE[target]) <= int(PIECE_VALUE[attacker]):\n            see = _see_capture_ordering(board, move)\n        see = max(-1_500, min(1_500, see))\n        score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker]) + 32 * see\n"
    rep(old, new)

    old = "        if target:\n            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"
    new = "        if target:\n            see = int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n            if int(PIECE_VALUE[target]) <= int(PIECE_VALUE[attacker]):\n                see = _see_capture_ordering(board, move)\n            see = max(-1_500, min(1_500, see))\n            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker]) + 32 * see\n"
    rep(old, new)

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
