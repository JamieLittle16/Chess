#!/usr/bin/env python3
"""Make V18's existing late-quiet futility aware of same-side static-eval improvement."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    def rep(old: str, new: str, count: int = 1) -> None:
        nonlocal s
        actual = s.count(old)
        if actual != count:
            raise RuntimeError(f"anchor count {actual} != {count}: {old[:120]!r}")
        s = s.replace(old, new, count)

    rep(
        "    pruning_static_eval = INFINITY\n"
        "    if (\n"
        "        depth <= 3\n",
        "    pruning_static_eval = INFINITY\n"
        "    improving = False\n"
        "    if (\n"
        "        depth <= 3\n",
    )
    rep(
        "        pruning_static_eval = _evaluate_state(side, eval_stack[ply])\n"
        "        if pruning_static_eval - 120 * depth >= beta:\n",
        "        pruning_static_eval = _evaluate_state(side, eval_stack[ply])\n"
        "        if ply >= 2:\n"
        "            improving = pruning_static_eval > _evaluate_state(side, eval_stack[ply - 2])\n"
        "        if pruning_static_eval - 120 * depth >= beta:\n",
    )
    rep(
        "            and index >= 4\n"
        "            and quiet\n",
        "            and index >= (6 if improving else 4)\n"
        "            and quiet\n",
    )

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
