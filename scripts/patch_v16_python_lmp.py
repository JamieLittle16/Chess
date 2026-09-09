#!/usr/bin/env python3
"""Add shallow scout-node late-move pruning to exact packaged V14.

Only genuinely late quiet non-killer moves are candidates. The move is made before pruning so
direct checks are preserved exactly. Thresholds are zero-based move indices for depths 1..3.
"""
from pathlib import Path
import sys

if len(sys.argv) != 5:
    raise SystemExit("usage: patch_v16_python_lmp.py SEARCH.py D1 D2 D3")
p = Path(sys.argv[1])
d1, d2, d3 = map(int, sys.argv[2:])
s = p.read_text()
anchor = '''        futility_candidate = (\n            pruning_static_eval != INFINITY\n            and depth <= 2\n            and index >= 4\n            and quiet\n            and not protected_killer\n            and abs(alpha) < MATE_THRESHOLD\n            and pruning_static_eval + 180 * depth <= alpha\n        )\n        # Check status only matters when this quiet could actually be reduced or pruned. Avoiding\n        # the attack test for early/non-reduced quiets preserves exact search semantics while\n        # removing work from one of the hottest recursive paths.\n        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate)\n        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False\n        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared\n'''
replacement = f'''        futility_candidate = (\n            pruning_static_eval != INFINITY\n            and depth <= 2\n            and index >= 4\n            and quiet\n            and not protected_killer\n            and abs(alpha) < MATE_THRESHOLD\n            and pruning_static_eval + 180 * depth <= alpha\n        )\n        # Conservative shallow late-move pruning. The move is already made, so checking quiets are\n        # preserved exactly. Tactical moves, killers, in-check nodes and PV/full-window nodes stay.\n        lmp_threshold = {d1} if depth <= 1 else ({d2} if depth == 2 else {d3})\n        lmp_candidate = (\n            depth <= 3\n            and beta == alpha_original + 1\n            and not checked\n            and quiet\n            and not protected_killer\n            and index >= lmp_threshold\n            and abs(alpha) < MATE_THRESHOLD\n        )\n        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate or lmp_candidate)\n        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False\n        if lmp_candidate and not gives_check:\n            undo_move_inplace(board, side, move, captured_piece, captured_square)\n            continue\n        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared\n'''
count = s.count(anchor)
if count != 1:
    raise SystemExit(f"expected one LMP insertion anchor, found {count}")
p.write_text(s.replace(anchor, replacement, 1))
print(f"patched shallow LMP thresholds: {d1}, {d2}, {d3}")
