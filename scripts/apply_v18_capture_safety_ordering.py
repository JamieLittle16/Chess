#!/usr/bin/env python3
"""Apply conservative occupancy-aware losing-capture ordering to exact PUNCH133."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--band", choices=("after_killers", "last"), required=True)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    anchor = """@njit(cache=False)\ndef _move_order_score_meta(board: np.ndarray, move: int, preferred: int) -> int:\n"""
    helper = """@njit(cache=False)\ndef _obviously_losing_capture(board: np.ndarray, move: int) -> bool:\n    \"\"\"Conservative SEE pre-screen used for ordering only.\n\n    A capture is called obviously losing only when a strictly more valuable non-promoting\n    attacker takes a lower-value victim and the destination is defended *after* occupancy is\n    updated.  This catches x-ray defenders exposed by the capture.  It intentionally does not\n    prune the move and does not classify equal-value captures, promotions or en-passant as bad.\n    \"\"\"\n    from_square = move_from(move)\n    to_square = move_to(move)\n    moving_signed = int(board[from_square])\n    attacker = abs(moving_signed)\n    promotion = move_promotion(move)\n    if promotion != 0:\n        return False\n\n    ep = bool(move & FLAG_EP)\n    captured_square = to_square\n    captured_signed = int(board[to_square])\n    if ep:\n        captured_square = to_square - 8 * (WHITE if moving_signed > 0 else -WHITE)\n        captured_signed = int(board[captured_square])\n    victim = abs(captured_signed)\n    if victim == EMPTY or int(PIECE_VALUE[victim]) >= int(PIECE_VALUE[attacker]):\n        return False\n\n    # Evaluate defenders in the post-capture occupancy, so vacating the origin can reveal x-rays.\n    old_to = int(board[to_square])\n    old_cap = int(board[captured_square])\n    board[from_square] = EMPTY\n    if ep:\n        board[captured_square] = EMPTY\n    board[to_square] = moving_signed\n    side = WHITE if moving_signed > 0 else -WHITE\n    defended = is_square_attacked(board, to_square, -side)\n    board[from_square] = moving_signed\n    board[to_square] = old_to\n    if ep:\n        board[captured_square] = old_cap\n    return defended\n\n\n@njit(cache=False)\ndef _move_order_score_meta(board: np.ndarray, move: int, preferred: int) -> int:\n"""
    if s.count(anchor) != 1:
        raise RuntimeError(f"helper anchor count {s.count(anchor)}, expected 1")
    s = s.replace(anchor, helper, 1)

    old = """        if target:\n            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"""
    if args.band == "after_killers":
        # Search after killers but before ordinary quiet history.
        new = """        if target:\n            if _obviously_losing_capture(board, move):\n                score += 4_700_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n            else:\n                score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"""
    else:
        # Bad captures come after quiets, Stockfish-style in spirit; still fully searched.
        new = """        if target:\n            if _obviously_losing_capture(board, move):\n                score += -1_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n            else:\n                score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n"""
    if s.count(old) != 1:
        raise RuntimeError(f"capture score anchor count {s.count(old)}, expected 1")
    p.write_text(s.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
