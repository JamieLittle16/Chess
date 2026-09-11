#!/usr/bin/env python3
"""Stage only risky main-search captures using conservative ordering-only SEE.

Qsearch/generic ordering stays untouched. Preferred moves stay preferred. Losing captures are
searched after quiets, never pruned, and cannot become killers.
"""
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
            raise RuntimeError(f"anchor count {actual} != {count}: {old[:120]!r}")
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
    """Swap-off estimate for ordering only. The caller invokes it only on risky captures."""
    from_square = move_from(move)
    to_square = move_to(move)
    signed_attacker = int(board[from_square])
    side = 1 if signed_attacker > 0 else -1
    attacker = abs(signed_attacker)
    captured_signed = int(board[to_square])
    captured = abs(captured_signed)
    if captured == EMPTY:
        return 0

    gains = np.empty(32, dtype=np.int32)
    sources = np.empty(31, dtype=np.int32)
    source_pieces = np.empty(31, dtype=np.int32)
    old_targets = np.empty(31, dtype=np.int32)
    gains[0] = int(PIECE_VALUE[captured])

    board[from_square] = EMPTY
    board[to_square] = side * attacker

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
    board[to_square] = captured_signed

    for back in range(depth, 0, -1):
        gains[back - 1] = -max(-gains[back - 1], gains[back])
    return int(gains[0])


'''
    rep(anchor, helpers + anchor)

    old = """        packed = _move_order_score_meta(board, move, preferred)
        score = packed >> 2
        meta = packed & 3
        if score < 5_040_000:
"""
    new = """        packed = _move_order_score_meta(board, move, preferred)
        score = packed >> 2
        meta = packed & 3
        # MAIN-SEE-STAGE: preserve the TT/root preference and all special tactical moves.
        # Ordinary captures whose victim is at least as valuable as the attacker are trivially
        # non-losing at threshold zero, so only expensive-piece-for-cheap-piece captures pay SEE.
        if move != preferred and (meta & 2) != 0 and move_promotion(move) == 0 and not (move & FLAG_EP):
            target = abs(int(board[move_to(move)]))
            attacker = abs(int(board[move_from(move)]))
            if target != 0 and int(PIECE_VALUE[target]) < int(PIECE_VALUE[attacker]):
                if _see_capture_ordering(board, move) < 0:
                    score = -2_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker]) + int(ORDER_CENTER_BONUS[move_to(move)])
        # Once captures may live below the quiet band, killer/history bonuses must be quiet-only.
        if score < 5_040_000 and (meta & 2) == 0:
"""
    rep(old, new)

    # A demoted capture that later refutes a line must not enter the quiet killer table.
    rep(
        "            if order_score < 5_590_000:\n",
        "            if quiet and order_score < 5_590_000:\n",
    )

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
