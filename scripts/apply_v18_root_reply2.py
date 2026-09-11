#!/usr/bin/env python3
"""Add high-material reply-aware root ordering; never prune a legal root move."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    needle = '''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''
    block = '''    # ROOT-REPLY2: high-material root-only reply-aware ordering for ordinary quiets.\n    # Blend the current one-ply static signal with the opponent's best immediate static reply.\n    # This changes ordering only; every legal root move is still searched normally.\n    if int(eval_stack[0, EVAL_PHASE]) >= 18:\n        root_static = _evaluate_state(side, eval_stack[0])\n        for policy_index in range(count):\n            packed_policy = int(score_stack[0, policy_index])\n            if (packed_policy & 2) == 0 and int(moves[policy_index]) != preferred:\n                policy_move = int(moves[policy_index])\n                _advance_eval_state_into(board, side, policy_move, eval_stack[0], eval_stack[1])\n                child_static = -_evaluate_state(-side, eval_stack[1])\n                child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n                    board, side, castling, ep_square, policy_move\n                )\n                reply_count = _legal_moves_for_state(\n                    board, -side, child_castling, child_ep,\n                    pseudo_stack[1], move_stack[1], eval_stack[1]\n                )\n                if reply_count == 0:\n                    if _state_in_check(board, -side, eval_stack[1]):\n                        reply_floor = MATE - 1\n                    else:\n                        reply_floor = 0\n                else:\n                    reply_floor = INFINITY\n                    for reply_index in range(reply_count):\n                        reply_move = int(move_stack[1, reply_index])\n                        _advance_eval_state_into(\n                            board, -side, reply_move, eval_stack[1], eval_stack[2]\n                        )\n                        reply_static = _evaluate_state(side, eval_stack[2])\n                        if reply_static < reply_floor:\n                            reply_floor = reply_static\n                undo_move_inplace(board, side, policy_move, captured_piece, captured_square)\n                child_delta = child_static - root_static\n                reply_delta = reply_floor - root_static\n                if child_delta > 300:\n                    child_delta = 300\n                elif child_delta < -300:\n                    child_delta = -300\n                if reply_delta > 300:\n                    reply_delta = 300\n                elif reply_delta < -300:\n                    reply_delta = -300\n                reply_prior = child_delta * 2 + reply_delta * 2\n                score_stack[0, policy_index] = (\n                    ((packed_policy >> 2) + reply_prior) * 4 + (packed_policy & 3)\n                )\n\n'''
    repl = '''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n''' + block + '''    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''
    actual = s.count(needle)
    if actual != 1:
        raise RuntimeError(f"root anchor count {actual} != 1")
    p.write_text(s.replace(needle, repl, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
