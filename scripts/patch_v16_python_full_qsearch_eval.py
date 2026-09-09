#!/usr/bin/env python3
"""Keep the full V14 learned evaluator active at every qsearch stand-pat.

Packaged V14 evaluates qsearch entry with H64+V13 but falls back to V13-only from
qply 1 onward. The learned H64 accumulator is already incrementally maintained for
those positions, so this patch changes only the output evaluation choice and leaves
qsearch move generation, ceiling, draw handling and alpha-beta semantics untouched.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = """        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n"""
NEW = """        stand_pat = _evaluate_state(side, eval_stack[ply])\n"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    text = args.path.read_text()
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one qsearch fallback block, found {count}")
    args.path.write_text(text.replace(OLD, NEW))
    print("patched qsearch stand-pat to use full learned evaluator at every qply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
