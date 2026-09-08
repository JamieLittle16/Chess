#!/usr/bin/env python3
"""Make a full-strength compact student evaluator coherent with search.

Packaged V14 intentionally evaluates its tiny student only at qsearch ply zero and advances only the
V13 prefix below that point.  That is a useful speed trick for a 1/12 residual, but it creates a
large evaluation discontinuity when the student approximates the full Rust Gestalt correction.
This patch therefore keeps the compact student live through tactical qsearch and uses the same full
static evaluator for RFP/late-futility calibration.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_coherent_student_eval.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n'''
new = '''        stand_pat = _evaluate_state(side, eval_stack[ply])\n'''
if s.count(old) != 1:
    raise SystemExit(f"qsearch stand-pat anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing\n        # qualified incremental updater performs no work in its appended student-accumulator tail.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n'''
new = '''        # The stronger compact student remains live through tactical qsearch so consecutive\n        # stand-pat scores come from one coherent evaluator rather than switching back to V13.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply],\n            eval_stack[ply + 1],\n        )\n'''
if s.count(old) != 1:
    raise SystemExit(f"qsearch evaluator advance anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])\n'''
new = '''        pruning_static_eval = _evaluate_state(side, eval_stack[ply])\n'''
if s.count(old) != 1:
    raise SystemExit(f"RFP static-eval anchor count={s.count(old)}")
s = s.replace(old, new, 1)

p.write_text(s)
print("patched coherent compact evaluator", p)
