#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) not in (2, 3):
    raise SystemExit('usage: apply_v18_root_value.py SEARCH.py [weight]')
p = Path(sys.argv[1])
weight = int(sys.argv[2]) if len(sys.argv) == 3 else 4
if weight <= 0:
    raise SystemExit('weight must be positive')
s = p.read_text()
needle = '''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''
block = f'''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n    # Root-only one-ply static value prior. It changes ordering, never evaluation.\n    root_static = _evaluate_state(side, eval_stack[0])\n    for policy_index in range(count):\n        packed_policy = int(score_stack[0, policy_index])\n        if (packed_policy & 2) == 0 and int(moves[policy_index]) != preferred:\n            policy_move = int(moves[policy_index])\n            _advance_eval_state_into(board, side, policy_move, eval_stack[0], eval_stack[1])\n            child_static = -_evaluate_state(-side, eval_stack[1])\n            policy_delta = child_static - root_static\n            if policy_delta > 300:\n                policy_delta = 300\n            elif policy_delta < -300:\n                policy_delta = -300\n            score_stack[0, policy_index] = ((packed_policy >> 2) + policy_delta * {weight}) * 4 + (packed_policy & 3)\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''
if s.count(needle) != 1:
    raise SystemExit(f'root-value patch mismatch: {s.count(needle)}')
p.write_text(s.replace(needle, block, 1))
