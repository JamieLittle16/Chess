#!/usr/bin/env python3
"""Use the learned H64 evaluator throughout tactical qsearch, not only at qply zero."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    old_eval = """        stand_pat = (\n            _evaluate_state(side, eval_stack[ply])\n            if qply == 0\n            else _evaluate_state_v13_only(side, eval_stack[ply])\n        )\n"""
    new_eval = """        # Q-H64 experiment: qsearch now keeps the learned accumulator current across\n        # tactical moves, so every stand-pat can use the same production evaluator.\n        stand_pat = _evaluate_state(side, eval_stack[ply])\n"""
    if s.count(old_eval) != 1:
        raise RuntimeError(f"qsearch stand-pat anchor count {s.count(old_eval)}, expected 1")
    s = s.replace(old_eval, new_eval, 1)

    old_advance = """        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n"""
    new_advance = """        # Tactical qsearch is much smaller than the normal tree. Pay the 64-lane\n        # incremental H64 update here so tactical leaf comparisons do not silently fall back to V13.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply],\n            eval_stack[ply + 1],\n        )\n"""
    if s.count(old_advance) != 1:
        raise RuntimeError(f"qsearch eval-advance anchor count {s.count(old_advance)}, expected 1")
    s = s.replace(old_advance, new_advance, 1)

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
