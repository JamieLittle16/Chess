#!/usr/bin/env python3
"""Avoid reloading ordinary quiet history after it was already folded into the order score.

For an ordinary non-killer quiet, _move_order_score contributes only ORDER_CENTER_BONUS[to] and the
Rust-history ordering layer adds exactly main+continuation history. Therefore the LMR history value
is recovered exactly as order_score - centre_bonus. Special quiet seventh-rank pushes live in a
separate 5.2M band where ordering intentionally does not add history, so they keep the old lookup.

Intended semantics: exact fixed-node identity.
"""
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit('usage: patch_v16_python_history_score_reuse.py SEARCH.py')
p=Path(sys.argv[1]);s=p.read_text()
n0=s.index('@njit(cache=False)\ndef _negamax(');n1=s.index('\n\n@njit(cache=False)\ndef _root(',n0);n=s[n0:n1]
old='''        move_history_score = _quiet_history_score(side, previous_context, current_move_context, quiet_history)
        reduction = _history_adjusted_lmr_reduction(depth, index, move_history_score) if lmr_candidate else 0
'''
new='''        # Ordinary quiet ordering already contains exactly main+continuation history on top of the
        # destination centre bonus. Reuse it instead of touching the two history tables again.
        if quiet and order_score < 5_040_000:
            move_history_score = order_score - int(ORDER_CENTER_BONUS[move_to(move)])
        elif quiet:
            # The defender-safe seventh-rank quiet band deliberately bypasses history in ordering.
            move_history_score = _quiet_history_score(
                side, previous_context, current_move_context, quiet_history
            )
        else:
            move_history_score = 0
        reduction = _history_adjusted_lmr_reduction(depth, index, move_history_score) if lmr_candidate else 0
'''
if n.count(old)!=1:raise SystemExit(f'history score anchor count={n.count(old)}')
n=n.replace(old,new,1);s=s[:n0]+n+s[n1:];p.write_text(s)
