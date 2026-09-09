#!/usr/bin/env python3
"""Retune V14's verified LMR schedule without changing verification semantics."""
from pathlib import Path
import sys

if len(sys.argv) != 8:
    raise SystemExit("usage: patch_v16_python_lmr_schedule.py SEARCH.py D1 M1 D2 M2 D3 M3")

p = Path(sys.argv[1])
d1, m1, d2, m2, d3, m3 = map(int, sys.argv[2:])
s = p.read_text()
old = '''@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n    """Accepted Rust adaptive verified-LMR schedule, zero-based move index."""\n    if depth >= 9 and move_index >= 12:\n        return 3\n    if depth >= 6 and move_index >= 8:\n        return 2\n    if depth >= 3 and move_index >= 4:\n        return 1\n    return 0\n'''
new = f'''@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n    """V16 Python-qualified verified-LMR schedule, zero-based move index."""\n    if depth >= {d3} and move_index >= {m3}:\n        return 3\n    if depth >= {d2} and move_index >= {m2}:\n        return 2\n    if depth >= {d1} and move_index >= {m1}:\n        return 1\n    return 0\n'''
count = s.count(old)
if count != 1:
    raise SystemExit(f"LMR schedule anchor count={count}")
p.write_text(s.replace(old, new, 1))
print(f"patched LMR schedule: d1/m1={d1}/{m1}, d2/m2={d2}/{m2}, d3/m3={d3}/{m3}")
