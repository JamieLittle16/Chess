#!/usr/bin/env python3
"""Use the full H64/V13 evaluator for the existing shallow RFP/futility oracle."""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = 'pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])'
new = 'pruning_static_eval = _evaluate_state(side, eval_stack[ply])'
if s.count(old) != 1:
    raise SystemExit(f'pruning oracle anchor count={s.count(old)}')
p.write_text(s.replace(old, new, 1))
