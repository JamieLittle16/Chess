#!/usr/bin/env python3
"""Align Python RFP/late-quiet pruning static evaluation with Rust V15.

The search policy is unchanged; only the already-computed H64/V13 full static evaluator replaces the
classical-only oracle on the same shallow scout nodes.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])'
new='pruning_static_eval = _evaluate_state(side, eval_stack[ply])'
if s.count(old)!=1:
    raise SystemExit(f'pruning oracle anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
