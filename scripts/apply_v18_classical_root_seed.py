#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''            else:\n                fallback_score = -_evaluate_state(-side, eval_stack[1])\n'''
new = '''            else:\n                # The emergency root seed is an ordering hint, not the searched evaluation.\n                # Use the robust classical+residual V13 score here so a small learned correction\n                # cannot give one quiet root move a 10M preferred-move ordering head start.\n                fallback_score = -_evaluate_state_v13_only(-side, eval_stack[1])\n'''
if s.count(old) != 1:
    raise SystemExit(f'classical-root-seed patch mismatch: {s.count(old)}')
p.write_text(s.replace(old, new, 1))
