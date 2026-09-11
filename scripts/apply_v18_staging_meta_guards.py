#!/usr/bin/env python3
"""Make killer/history eligibility follow tactical metadata instead of numeric score bands."""
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
            raise RuntimeError(f"anchor count {actual} != {count}: {old[:100]!r}")
        s = s.replace(old, new, count)

    rep(
        "        if score < 5_040_000:\n"
        "            if move == killer0:\n"
        "                score += 5_000_000\n"
        "            elif move == killer1:\n"
        "                score += 4_900_000\n"
        "            elif (meta & 2) == 0:\n"
        "                context = _quiet_history_context(board, move)\n"
        "                score += _quiet_history_score(side, previous_context, context, quiet_history)\n",
        "        if (meta & 2) == 0:\n"
        "            if move == killer0:\n"
        "                score += 5_000_000\n"
        "            elif move == killer1:\n"
        "                score += 4_900_000\n"
        "            else:\n"
        "                context = _quiet_history_context(board, move)\n"
        "                score += _quiet_history_score(side, previous_context, context, quiet_history)\n",
    )
    rep("            if order_score < 5_590_000:\n", "            if quiet:\n")

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
