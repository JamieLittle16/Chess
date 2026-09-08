#!/usr/bin/env python3
"""Carry only V13 through ordinary negamax and rebuild H64 at first qsearch entry.

This is the deliberately simple full-path lazy baseline. H64 is not consulted by ordinary negamax:
TT, legality/check status, RFP, LMR, futility and move ordering all use the V13 prefix or board state.
Only qply==0 stand-pat consumes the H64 student. Interior search therefore advances exactly the
8-cell V13 prefix and reconstructs the absolute768 accumulator from the current board only when the
line genuinely reaches quiescence.

The transformation is intended to be semantically exact. The absolute768 accumulator is an integer
sum of piece-square rows plus bias, so rebuilding it from the board must equal repeated incremental
transport bit-for-bit.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

# Materialise H64 immediately before the sole ordinary-search entry into qply 0.
old = '''    if depth <= 0:\n        return _quiescence(\n'''
new = '''    if depth <= 0:\n        # H64 is consumed only by qply==0 stand-pat. Rebuild it once for lines that actually\n        # survive ordinary search to quiescence; all earlier TT/pruning cutoffs avoid H64 work.\n        build_absolute768_accumulator_into(\n            board,\n            STUDENT_FEATURE_WEIGHTS,\n            STUDENT_FEATURE_BIAS,\n            eval_stack[ply, STUDENT_OFFSET:EVAL_WIDTH],\n        )\n        return _quiescence(\n'''
if s.count(old) != 1:
    raise SystemExit(f"depth-zero anchor count={s.count(old)}")
s = s.replace(old, new, 1)

# Only alter the child-state transport inside _negamax. Root/fallback paths remain eager and qsearch
# already advances V13-only below qply 0 in packaged V14.
start = s.index('def _negamax(')
needle = '        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n'
pos = s.find(needle, start)
if pos < 0:
    raise SystemExit('negamax full-state transport anchor not found')
replacement = '''        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n'''
s = s[:pos] + s[pos:].replace(needle, replacement, 1)

p.write_text(s)
