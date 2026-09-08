#!/usr/bin/env python3
"""Use the V14 H64 student through a bounded number of qsearch plies.

DEPTH is the maximum qply whose stand-pat uses the full V14 evaluator. qply 0 is already full in V14;
DEPTH=1 therefore makes the first tactical child full as well. Child accumulator transport is paid
only when the next qply will consume it.
"""
from pathlib import Path
import sys

if len(sys.argv)!=3: raise SystemExit('usage: patch_v15_python_qsearch_student_depth.py SEARCH.py DEPTH')
p=Path(sys.argv[1]);depth=int(sys.argv[2])
if depth not in (1,2,6): raise SystemExit('DEPTH must be 1, 2 or 6')
s=p.read_text()
old='''        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
'''
new=f'''        if qply <= {depth}:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
'''
if s.count(old)!=1: raise SystemExit(f'stand-pat anchor count={s.count(old)}')
s=s.replace(old,new,1)
old2='''        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
        # qualified incremental updater performs no work in its appended student-accumulator tail.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
'''
new2=f'''        # Carry the H64 tail only when the next qsearch ply will actually consume it.
        if qply < {depth}:
            _advance_eval_state_into(board,side,move,eval_stack[ply],eval_stack[ply+1])
        else:
            _advance_eval_state_into(
                board,side,move,
                eval_stack[ply,:EVAL_V13_WIDTH],eval_stack[ply+1,:EVAL_V13_WIDTH],
            )
'''
if s.count(old2)!=1: raise SystemExit(f'qsearch transport anchor count={s.count(old2)}')
s=s.replace(old2,new2,1)
p.write_text(s)
