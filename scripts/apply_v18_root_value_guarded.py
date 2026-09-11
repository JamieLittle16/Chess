#!/usr/bin/env python3
"""Apply a guarded root one-ply value-ordering variant for opening qualification."""
from __future__ import annotations

import os
import sys
from pathlib import Path

VARIANT = os.environ.get("ROOT_VALUE_VARIANT", "depth2")
CONFIG = {
    "depth2": (2, 300, 4),
    "depth4cap80": (4, 80, 4),
    "globalcap40": (99, 40, 4),
}[VARIANT]
MAX_DEPTH, CLAMP, WEIGHT = CONFIG

NEEDLE = '''    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)\n'''

BLOCK = f'''    # ROOT-VALUE-GUARDED ({VARIANT}): shallow one-ply ordering only; search scores unchanged.\n    if depth <= {MAX_DEPTH}:\n        root_static = _evaluate_state(side, eval_stack[0])\n        for policy_index in range(count):\n            packed_policy = int(score_stack[0, policy_index])\n            if (packed_policy & 2) == 0 and int(moves[policy_index]) != preferred:\n                policy_move = int(moves[policy_index])\n                _advance_eval_state_into(board, side, policy_move, eval_stack[0], eval_stack[1])\n                child_static = -_evaluate_state(-side, eval_stack[1])\n                policy_delta = child_static - root_static\n                if policy_delta > {CLAMP}:\n                    policy_delta = {CLAMP}\n                elif policy_delta < -{CLAMP}:\n                    policy_delta = -{CLAMP}\n                score_stack[0, policy_index] = (((packed_policy >> 2) + policy_delta * {WEIGHT}) * 4) + (packed_policy & 3)\n\n'''


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_v18_root_value_guarded.py PATH/TO/numba_search.py")
    p = Path(sys.argv[1])
    s = p.read_text()
    if "# ROOT-VALUE-GUARDED" in s:
        raise SystemExit("guarded root-value patch already present")
    if s.count(NEEDLE) != 1:
        raise SystemExit(f"expected exactly one root insertion point, got {s.count(NEEDLE)}")
    replacement = NEEDLE.replace("\n\n    _pick_next_scored_move", "\n" + BLOCK + "    _pick_next_scored_move")
    p.write_text(s.replace(NEEDLE, replacement, 1))
    print("applied", VARIANT, "depth", MAX_DEPTH, "clamp", CLAMP, "weight", WEIGHT)


if __name__ == "__main__":
    main()
