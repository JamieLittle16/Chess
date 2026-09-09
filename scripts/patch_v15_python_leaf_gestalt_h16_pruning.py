#!/usr/bin/env python3
"""Let the distilled Rust Gestalt student drive shallow scout pruning.

Apply after patch_v15_python_leaf_gestalt_h16.py (and normally after the qall upgrade). Rust V15
uses its Gestalt leaf evaluator for the reverse-futility static evaluation, and the same value then
controls late-quiet futility. Packaged Python V14 intentionally used only its classical term there.
This patch closes that policy gap without changing the RFP/LQF margins or eligibility gates.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_leaf_gestalt_h16_pruning.py SEARCH.py")
p=Path(sys.argv[1]); s=p.read_text()
old="pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])"
new="pruning_static_eval = _evaluate_state_leaf_gestalt(board, side, eval_stack[ply])"
if s.count(old)!=1:
    raise SystemExit(f"pruning static-eval anchor count={s.count(old)}")
s=s.replace(old,new,1)
p.write_text(s)
