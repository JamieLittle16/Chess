#!/usr/bin/env python3
"""Add qsearch-verified shallow razoring to exact packaged V14."""
from pathlib import Path
import sys
if len(sys.argv)!=5: raise SystemExit('usage: patch_v15_python_razoring.py SEARCH.py MAX_DEPTH MARGIN1 MARGIN2')
p=Path(sys.argv[1]);max_depth,m1,m2=map(int,sys.argv[2:]);s=p.read_text()
anchor='''    checked = _state_in_check(board, side, eval_stack[ply])
    # Conservative reverse-futility pruning ported from the accepted Rust policy. Rule draws and
'''
insert=f'''    checked = _state_in_check(board, side, eval_stack[ply])
    if (
        depth <= {max_depth}
        and beta == alpha + 1
        and not checked
        and abs(alpha) < MATE_THRESHOLD
    ):
        razor_margin = {m1} if depth <= 1 else {m2}
        razor_static = _evaluate_state_v13_only(side, eval_stack[ply])
        if razor_static + razor_margin <= alpha:
            razor_score, razor_aborted = _quiescence(
                board, side, castling, ep_square, halfmove_clock,
                alpha, beta, ply, 1, nodes, max_nodes, hard_deadline_ticks,
                pseudo_stack, move_stack, score_stack, eval_stack,
                history_keys, history_count, path_keys,
            )
            if razor_aborted:
                return 0, True
            if razor_score <= alpha:
                return razor_score, False

    # Conservative reverse-futility pruning ported from the accepted Rust policy. Rule draws and
'''
if s.count(anchor)!=1:raise SystemExit(f'razor insertion anchor count={s.count(anchor)}')
p.write_text(s.replace(anchor,insert,1))
