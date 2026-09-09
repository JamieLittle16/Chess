#!/usr/bin/env python3
"""Upgrade the leaf-only H16 Gestalt patch from qply-0-only to every non-check qsearch stand-pat.

Apply after patch_v15_python_leaf_gestalt_h16.py. The richer student is rebuilt directly from the
current board, so unlike V14's incrementally-carried H64 tail it remains valid after tactical qsearch
moves without any extra accumulator transport.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_leaf_gestalt_h16_qall.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()
old = """        if qply == 0:
            stand_pat = _evaluate_state_leaf_gestalt(board, side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
"""
new = """        stand_pat = _evaluate_state_leaf_gestalt(board, side, eval_stack[ply])
"""
if s.count(old) != 1:
    raise SystemExit(f"qsearch leaf anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
