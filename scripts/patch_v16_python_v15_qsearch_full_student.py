#!/usr/bin/env python3
"""Keep the exact V15 H64 student coherent and active throughout qsearch."""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

old = '''        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
'''
new = '''        stand_pat = _evaluate_state(side, eval_stack[ply])
'''
if s.count(old) != 1:
    raise SystemExit(f'stand-pat anchor count={s.count(old)}')
s = s.replace(old, new, 1)

old = '''        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
        # qualified incremental updater performs no work in its appended student-accumulator tail.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
'''
new = '''        # The H64 state is materialized once at the nominal-search/qsearch boundary. Keep it
        # coherent through tactical descendants so every stand-pat uses the same learned evaluator.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply],
            eval_stack[ply + 1],
        )
'''
if s.count(old) != 1:
    raise SystemExit(f'qsearch accumulator anchor count={s.count(old)}')
s = s.replace(old, new, 1)

p.write_text(s)
