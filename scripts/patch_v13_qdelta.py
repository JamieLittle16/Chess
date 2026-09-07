#!/usr/bin/env python3
"""Patch exact V13 qsearch with conservative non-check delta pruning."""
from __future__ import annotations
import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return source.replace(old, new, 1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--margin", type=int, required=True)
    args = ap.parse_args()
    if args.margin < 0:
        raise SystemExit("margin must be non-negative")
    p = args.path
    s = p.read_text()

    loop_anchor = (
        "    for index in range(count):\n"
        "        move = int(moves[index])\n"
        "        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n"
    )
    loop_new = (
        "    for index in range(count):\n"
        "        move = int(moves[index])\n"
        "        delta_prune = False\n"
        "        if not checked and qply >= 1 and move_promotion(move) == 0:\n"
        "            to_square = move_to(move)\n"
        "            captured_value_piece = abs(int(board[to_square]))\n"
        "            if move & FLAG_EP:\n"
        "                captured_value_piece = PAWN\n"
        "            if captured_value_piece != EMPTY:\n"
        f"                if stand_pat + int(PIECE_VALUE[captured_value_piece]) + {args.margin} < alpha:\n"
        "                    delta_prune = True\n"
        "        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n"
    )
    s = replace_once(s, loop_anchor, loop_new, "qsearch move loop")

    make_anchor = (
        "        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n"
        "            board, side, castling, ep_square, move\n"
        "        )\n"
    )
    make_new = make_anchor + (
        "        if delta_prune and not _state_in_check(board, -side, eval_stack[ply + 1]):\n"
        "            undo_move_inplace(board, side, move, captured_piece, captured_square)\n"
        "            continue\n"
    )
    s = replace_once(s, make_anchor, make_new, "qsearch post-move check")

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
