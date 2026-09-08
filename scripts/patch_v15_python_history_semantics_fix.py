#!/usr/bin/env python3
"""Fix Search-v2 history gravity to match Rust signed division exactly.

Rust integer division truncates toward zero. Python's // floors negative values, so the original
port differed by one on many negative-history updates. This post-patch fix removes that semantic
drift before qualification.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_history_semantics_fix.py SEARCH.py")

p = Path(sys.argv[1])
s = p.read_text()
old = "    gravity = current * abs(bonus) // HISTORY_LIMIT\n"
new = """    product = current * abs(bonus)
    gravity = product // HISTORY_LIMIT if product >= 0 else -((-product) // HISTORY_LIMIT)
"""
if s.count(old) != 1:
    raise SystemExit(f"history gravity anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
