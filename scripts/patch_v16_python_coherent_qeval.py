#!/usr/bin/env python3
"""Use the existing full V14 evaluator at every non-check qsearch ply.

Rust V15 retains its learned leaf evaluator throughout qsearch. Packaged Python V14 uses its full
H64+V13 evaluator only at qply zero, then silently falls back to V13-only deeper in tactical lines.
The H64 accumulator is already advanced/restored for every qsearch move, so this changes only the
64-lane output arithmetic and evaluation semantics, not state maintenance.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
        if stand_pat >= beta:
'''
new='''    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
        stand_pat = _evaluate_state(side, eval_stack[ply])
        if stand_pat >= beta:
'''
if s.count(old)!=1:
    raise SystemExit(f'qsearch evaluator anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
