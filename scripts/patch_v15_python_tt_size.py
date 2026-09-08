#!/usr/bin/env python3
"""Resize the exact packaged V14 score/bound transposition table for qualification."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_tt_size.py SEARCH.py TT_BITS")
p = Path(sys.argv[1])
bits = int(sys.argv[2])
if bits < 18 or bits > 21:
    raise SystemExit("TT_BITS must be in [18, 21]")
s = p.read_text()
old = "TT_BITS = 18\nTT_SIZE = 1 << TT_BITS\n"
new = f"TT_BITS = {bits}\nTT_SIZE = 1 << TT_BITS\n"
if s.count(old) != 1:
    raise SystemExit(f"expected one TT size anchor, found {s.count(old)}")
p.write_text(s.replace(old, new, 1))
