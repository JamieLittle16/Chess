#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''            else:\n                fallback_score = -_evaluate_state(-side, eval_stack[1])\n'''
new = '''            else:\n                # The emergency/root seed is an ordering hint, not the searched evaluation.\n                # Use the robust classical+residual V13 score here so the learned student cannot\n                # give one quiet move an outsized preferred-move head start before real search.\n                fallback_score = -_evaluate_state_v13_only(-side, eval_stack[1])\n'''
count = s.count(old)
if count != 3:
    raise SystemExit(f'classical-root-seed patch mismatch: {count}')
p.write_text(s.replace(old, new))
