#!/usr/bin/env python3
"""Turn the existing ordering-only SEE score into true good/bad capture stages.

This deliberately changes ordering only: every legal capture is still searched.  Positive/equal
SEE captures retain the tactical band; negative SEE captures move behind quiet history/killers.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()
    old = "score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker]) + 32 * see"
    new = "score += (7_000_000 if see >= 0 else -1_000_000) + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])"
    n = s.count(old)
    if n != 2:
        raise RuntimeError(f"expected two SEE scoring sites, found {n}")
    p.write_text(s.replace(old, new))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
