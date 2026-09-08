#!/usr/bin/env python3
"""Retune V14's verified LMR schedule without changing verification semantics."""
from pathlib import Path
import sys
if len(sys.argv)!=8:raise SystemExit('usage: patch_v15_python_lmr_schedule.py SEARCH.py D1 M1 D2 M2 D3 M3')
p=Path(sys.argv[1]);d1,m1,d2,m2,d3,m3=map(int,sys.argv[2:]);s=p.read_text()
old='''@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
    """Accepted Rust adaptive verified-LMR schedule, zero-based move index."""
    if depth >= 9 and move_index >= 12:
        return 3
    if depth >= 6 and move_index >= 8:
        return 2
    if depth >= 3 and move_index >= 4:
        return 1
    return 0
'''
new=f'''@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
    """V15 Python-qualified verified-LMR schedule, zero-based move index."""
    if depth >= {d3} and move_index >= {m3}:
        return 3
    if depth >= {d2} and move_index >= {m2}:
        return 2
    if depth >= {d1} and move_index >= {m1}:
        return 1
    return 0
'''
if s.count(old)!=1:raise SystemExit(f'LMR schedule anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
