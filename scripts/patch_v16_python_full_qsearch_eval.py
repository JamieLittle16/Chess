#!/usr/bin/env python3
"""Keep the full V14 learned evaluator coherent and active throughout qsearch.

Packaged V14 evaluates qsearch entry with H64+V13 but deliberately advances only the
V13 prefix after qply 0, then evaluates deeper tactical positions with V13-only.  A
valid full-H64 experiment therefore has two inseparable changes:

1. advance the complete incremental evaluator state for every qsearch move; and
2. use the complete learned evaluator at every non-check stand-pat.

Move generation, qsearch ceiling, draw handling and alpha-beta semantics are unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD_STAND = """        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n"""
NEW_STAND = """        stand_pat = _evaluate_state(side, eval_stack[ply])\n"""

OLD_ADVANCE = """        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing\n        # qualified incremental updater performs no work in its appended student-accumulator tail.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n"""
NEW_ADVANCE = """        # Full-H64 qsearch experiment: keep the already-qualified incremental state coherent\n        # through tactical moves so deeper stand-pat calls never read stale student lanes.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply],\n            eval_stack[ply + 1],\n        )\n"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    text = args.path.read_text()
    if text.count(OLD_STAND) != 1:
        raise SystemExit(f"expected one qsearch stand-pat fallback block, found {text.count(OLD_STAND)}")
    if text.count(OLD_ADVANCE) != 1:
        raise SystemExit(f"expected one V13-only qsearch advance block, found {text.count(OLD_ADVANCE)}")
    text = text.replace(OLD_STAND, NEW_STAND, 1).replace(OLD_ADVANCE, NEW_ADVANCE, 1)
    args.path.write_text(text)
    print("patched qsearch to advance and evaluate the full learned state at every qply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
