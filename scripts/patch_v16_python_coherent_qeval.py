#!/usr/bin/env python3
"""Use the existing full V14 evaluator and accumulator at every qsearch ply.

Rust V15 retains its learned leaf evaluator throughout qsearch. Packaged Python V14 uses its full
H64+V13 evaluator only at qply zero, then both evaluates and incrementally advances only the V13
prefix deeper in tactical lines. A coherent experiment must change both together: full stand-pat
and full accumulator updates on qsearch children.
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
s=s.replace(old,new,1)
old='''        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
        # qualified incremental updater performs no work in its appended student-accumulator tail.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
'''
new='''        # Keep the H64 student state coherent with the child board throughout qsearch.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply],
            eval_stack[ply + 1],
        )
'''
if s.count(old)!=1:
    raise SystemExit(f'qsearch incremental-state anchor count={s.count(old)}')
s=s.replace(old,new,1)
p.write_text(s)
