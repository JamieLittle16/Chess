#!/usr/bin/env python3
"""Apply a calibrated learned one-ply root ordering prior to exact PUNCH133."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--scale", type=int, choices=(1, 2, 3, 4), required=True)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()
    old = """    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)"""
    new = f"""    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n    # V18 learned root prior: use the already-loaded value evaluator only as a\n    # gentle ordering signal for ordinary quiets. Search semantics are unchanged.\n    root_static = _evaluate_state(side, eval_stack[0])\n    for policy_index in range(count):\n        packed_policy = int(score_stack[0, policy_index])\n        if (packed_policy & 2) == 0 and int(moves[policy_index]) != preferred:\n            policy_move = int(moves[policy_index])\n            _advance_eval_state_into(board, side, policy_move, eval_stack[0], eval_stack[1])\n            child_static = -_evaluate_state(-side, eval_stack[1])\n            policy_delta = child_static - root_static\n            if policy_delta > 300:\n                policy_delta = 300\n            elif policy_delta < -300:\n                policy_delta = -300\n            score_stack[0, policy_index] = ((packed_policy >> 2) + policy_delta * {args.scale}) * 4 + (packed_policy & 3)\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)"""
    if s.count(old) != 1:
        raise RuntimeError(f"ROOT-VALUE anchor count {s.count(old)}, expected 1")
    p.write_text(s.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
