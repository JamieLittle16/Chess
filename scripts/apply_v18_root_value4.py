#!/usr/bin/env python3
"""Apply the screened ROOT-VALUE4 root-quiet ordering experiment."""
from __future__ import annotations

import sys
from pathlib import Path

BLOCK = '''    # ROOT-VALUE4: gentle learned one-ply ordering prior for ordinary root quiets.\n    root_static = _evaluate_state(side, eval_stack[0])\n    for policy_index in range(count):\n        packed_policy = int(score_stack[0, policy_index])\n        if (packed_policy & 2) == 0 and int(moves[policy_index]) != preferred:\n            policy_move = int(moves[policy_index])\n            _advance_eval_state_into(board, side, policy_move, eval_stack[0], eval_stack[1])\n            child_static = -_evaluate_state(-side, eval_stack[1])\n            policy_delta = child_static - root_static\n            if policy_delta > 300:\n                policy_delta = 300\n            elif policy_delta < -300:\n                policy_delta = -300\n            score_stack[0, policy_index] = (((packed_policy >> 2) + policy_delta * 4) * 4) + (packed_policy & 3)\n\n'''

NEEDLE = '''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_v18_root_value4.py PATH/TO/numba_search.py")
    p = Path(sys.argv[1])
    s = p.read_text()
    if "# ROOT-VALUE4:" in s:
        print("ROOT-VALUE4 already applied")
        return
    if s.count(NEEDLE) != 1:
        raise SystemExit(f"expected exactly one root-ordering insertion point, got {s.count(NEEDLE)}")
    replacement = NEEDLE.replace("\n\n    _pick_next_scored_move", "\n" + BLOCK + "    _pick_next_scored_move")
    p.write_text(s.replace(NEEDLE, replacement, 1))
    print("applied ROOT-VALUE4")


if __name__ == "__main__":
    main()
