#!/usr/bin/env python3
"""Add shallow scout-node late-move pruning to exact packaged V14."""
from pathlib import Path
import sys
if len(sys.argv)!=5: raise SystemExit('usage: patch_v15_python_lmp.py SEARCH.py D1 D2 D3')
p=Path(sys.argv[1]);d1,d2,d3=map(int,sys.argv[2:]);s=p.read_text()
anchor='''        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )
        # Check status only matters when this quiet could actually be reduced or pruned. Avoiding
        # the attack test for early/non-reduced quiets preserves exact search semantics while
        # removing work from one of the hottest recursive paths.
        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate)
        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False
        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared
'''
replacement=f'''        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )
        lmp_threshold = {d1} if depth <= 1 else ({d2} if depth == 2 else {d3})
        lmp_candidate = (
            depth <= 3
            and beta == alpha_original + 1
            and not checked
            and quiet
            and not protected_killer
            and index >= lmp_threshold
            and abs(alpha) < MATE_THRESHOLD
        )
        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate or lmp_candidate)
        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False
        if lmp_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue
        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared
'''
if s.count(anchor)!=1: raise SystemExit(f'LMP anchor count={s.count(anchor)}')
p.write_text(s.replace(anchor,replacement,1))
