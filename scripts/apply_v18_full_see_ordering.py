#!/usr/bin/env python3
"""Apply allocation-free swap-off SEE capture partitioning to exact PUNCH133."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    anchor = """@njit(cache=False)\ndef _move_order_score_meta(board: np.ndarray, move: int, preferred: int) -> int:\n"""
    helper = r'''@njit(cache=False, inline="always")
def _see_removed(mask: np.uint64, square: int) -> bool:
    return bool((mask >> np.uint64(square)) & np.uint64(1))


@njit(cache=False)
def _see_attacker_square(
    board: np.ndarray, target: int, side: int, piece_type: int, removed: np.uint64
) -> int:
    """Return one least-type pseudo-attacker under the supplied occupancy mask."""
    tf = target & 7
    tr = target >> 3

    if piece_type == PAWN:
        sr = tr - side
        if 0 <= sr < 8:
            sf = tf - 1
            if sf >= 0:
                sq = sr * 8 + sf
                if not _see_removed(removed, sq) and int(board[sq]) == side * PAWN:
                    return sq
            sf = tf + 1
            if sf < 8:
                sq = sr * 8 + sf
                if not _see_removed(removed, sq) and int(board[sq]) == side * PAWN:
                    return sq
        return -1

    if piece_type == KNIGHT:
        for df, dr in ((-2, -1), (-2, 1), (-1, -2), (-1, 2),
                       (1, -2), (1, 2), (2, -1), (2, 1)):
            sf = tf + df
            sr = tr + dr
            if 0 <= sf < 8 and 0 <= sr < 8:
                sq = sr * 8 + sf
                if not _see_removed(removed, sq) and int(board[sq]) == side * KNIGHT:
                    return sq
        return -1

    if piece_type == BISHOP or piece_type == ROOK or piece_type == QUEEN:
        for family in range(2):
            if piece_type == BISHOP and family != 0:
                continue
            if piece_type == ROOK and family != 1:
                continue
            for direction in range(4):
                if family == 0:
                    df = -1 if direction < 2 else 1
                    dr = -1 if (direction & 1) == 0 else 1
                else:
                    if direction == 0:
                        df, dr = -1, 0
                    elif direction == 1:
                        df, dr = 1, 0
                    elif direction == 2:
                        df, dr = 0, -1
                    else:
                        df, dr = 0, 1
                sf = tf + df
                sr = tr + dr
                while 0 <= sf < 8 and 0 <= sr < 8:
                    sq = sr * 8 + sf
                    if _see_removed(removed, sq):
                        sf += df
                        sr += dr
                        continue
                    signed_piece = int(board[sq])
                    if signed_piece != EMPTY:
                        if signed_piece == side * piece_type:
                            return sq
                        break
                    sf += df
                    sr += dr
        return -1

    # King is last in least-valuable-attacker order.
    for df, dr in ((-1, -1), (-1, 0), (-1, 1), (0, -1),
                   (0, 1), (1, -1), (1, 0), (1, 1)):
        sf = tf + df
        sr = tr + dr
        if 0 <= sf < 8 and 0 <= sr < 8:
            sq = sr * 8 + sf
            if not _see_removed(removed, sq) and int(board[sq]) == side * KING:
                return sq
    return -1


@njit(cache=False)
def _see_any_attacker(board: np.ndarray, target: int, side: int, removed: np.uint64) -> bool:
    for piece_type in (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING):
        if _see_attacker_square(board, target, side, piece_type, removed) >= 0:
            return True
    return False


@njit(cache=False)
def _see_ge_zero(board: np.ndarray, move: int) -> bool:
    """Allocation-free threshold SEE for ordinary captures, adapted to the array board.

    This mirrors the null-window swap-off structure used by modern engines.  Promotions and
    en-passant are deliberately accepted here; this first deployment is move ordering only.
    Pins are treated conservatively as attackers, which can only move a capture later, never prune it.
    """
    if (move & FLAG_EP) or move_promotion(move) != 0:
        return True
    from_square = move_from(move)
    to_square = move_to(move)
    moving_signed = int(board[from_square])
    captured_signed = int(board[to_square])
    if captured_signed == EMPTY:
        return True
    attacker = abs(moving_signed)
    if attacker == KING:
        return True  # legal king captures have already passed the attack test
    victim = abs(captured_signed)

    swap = int(PIECE_VALUE[victim])
    if swap < 0:
        return False
    swap = int(PIECE_VALUE[attacker]) - swap
    if swap <= 0:
        return True

    side = WHITE if moving_signed > 0 else -WHITE
    stm = side
    # Captured target and the initial attacker's source are empty for x-ray purposes.
    removed = (np.uint64(1) << np.uint64(from_square)) | (np.uint64(1) << np.uint64(to_square))
    res = 1

    while True:
        stm = -stm
        attacker_square = -1
        attacker_type = EMPTY
        for piece_type in (PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING):
            attacker_square = _see_attacker_square(board, to_square, stm, piece_type, removed)
            if attacker_square >= 0:
                attacker_type = piece_type
                break
        if attacker_square < 0:
            break

        res ^= 1
        if attacker_type == KING:
            removed |= np.uint64(1) << np.uint64(attacker_square)
            return bool((res ^ 1) if _see_any_attacker(board, to_square, -stm, removed) else res)

        swap = int(PIECE_VALUE[attacker_type]) - swap
        if swap < res:
            break
        removed |= np.uint64(1) << np.uint64(attacker_square)

    return bool(res)


@njit(cache=False)
def _move_order_score_meta(board: np.ndarray, move: int, preferred: int) -> int:
'''
    if s.count(anchor) != 1:
        raise RuntimeError(f"SEE helper anchor count {s.count(anchor)}, expected 1")
    s = s.replace(anchor, helper, 1)

    old = """        if target:\n            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"""
    new = """        if target:\n            # V18 FULL-SEE-ORDER: retain the accepted MVV/LVA ordering for good/equal\n            # captures, but place negative swap-off captures after ordinary quiets.  The\n            # move remains tactical and is still searched fully; this is ordering, not pruning.\n            if _see_ge_zero(board, move):\n                score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n            else:\n                score += -1_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"""
    if s.count(old) != 1:
        raise RuntimeError(f"capture score anchor count {s.count(old)}, expected 1")
    p.write_text(s.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
