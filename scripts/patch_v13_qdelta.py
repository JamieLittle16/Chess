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

    # Keep the rule deliberately conservative: never prune while in check, never at qply 0,
    # never promotions, and never a capture that gives check.  The bound uses only immediately
    # captured material plus a generous margin; positional terms are left entirely untrusted.
    old = "        stand_pat = _evaluate_state(side, eval_stack[ply])\n"
    if s.count(old) != 1:
        raise SystemExit(f"stand-pat anchor count={s.count(old)}")

    loop_anchor = "        for move_index in range(tactical_count):\n            move = int(tactical_moves[move_index])\n"
    loop_new = (
        "        for move_index in range(tactical_count):\n"
        "            move = int(tactical_moves[move_index])\n"
        "            delta_prune = False\n"
        "            if not checked and qply >= 1 and move_promotion(move) == 0:\n"
        "                to_square = move_to(move)\n"
        "                captured_piece = abs(int(board[to_square]))\n"
        "                if move & FLAG_EP:\n"
        "                    captured_piece = PAWN\n"
        "                if captured_piece != EMPTY:\n"
        f"                    if stand_pat + int(PIECE_VALUE[captured_piece]) + {args.margin} < alpha:\n"
        "                        delta_prune = True\n"
    )
    s = replace_once(s, loop_anchor, loop_new, "qsearch tactical loop")

    make_anchor = (
        "            next_castling, next_ep, captured, moved = make_move_inplace(\n"
        "                board, side, castling, ep_square, move\n"
        "            )\n"
        "            _advance_eval_state_into(board_before_move, side, move, eval_stack[ply], eval_stack[ply + 1])\n"
    )
    # The exact source updates eval state before/after make depending on the refactor version.  Do
    # not guess: if this anchor is absent, the CI log will expose the exact local sequence and fail
    # closed rather than silently installing unsafe pruning.
    if s.count(make_anchor) == 1:
        make_new = make_anchor + (
            "            if delta_prune and not _state_in_check(board, -side, eval_stack[ply + 1]):\n"
            "                undo_move_inplace(board, side, move, captured, moved)\n"
            "                continue\n"
        )
        s = replace_once(s, make_anchor, make_new, "qsearch post-move check")
    else:
        # Support the current JIT-refactored V13 layout, where eval state is advanced before the
        # board mutation and the undo tuple is explicit.
        marker = "            score = -_quiescence(\n"
        idx = s.find(marker)
        if idx < 0:
            raise SystemExit("qsearch recurse anchor missing")
        # Locate the nearest make_move_inplace call preceding recursive qsearch and insert the
        # check immediately after its completed statement.
        start = s.rfind("            next_castling, next_ep", 0, idx)
        if start < 0:
            raise SystemExit("qsearch make anchor missing")
        end = s.find("\n", s.find(")", start)) + 1
        snippet = s[start:end]
        if "make_move_inplace" not in snippet:
            raise SystemExit("unexpected qsearch make layout")
        insertion = snippet + (
            "            if delta_prune and not _state_in_check(board, -side, eval_stack[ply + 1]):\n"
            "                undo_move_inplace(board, side, move, captured, moved)\n"
            "                continue\n"
        )
        s = s[:start] + insertion + s[end:]

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
