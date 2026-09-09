#!/usr/bin/env python3
"""Reuse exact persistent main-search TT entries at the real root.

qTT uses TT depth values >= TT_QDEPTH_BASE for quiescence entries, so root reuse must explicitly
exclude that namespace. Only exact main-search entries with sufficient depth may skip an iterative
root pass.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
old='''    if (\n        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key\n        and tt_table[TT_CONTEXTS_OFFSET + root_tt_index] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n    _order_moves(board, moves, count, preferred, score_stack[0])\n'''
new='''    if (\n        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key\n        and tt_table[TT_CONTEXTS_OFFSET + root_tt_index] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n        root_tt_depth = _tt_meta_depth(root_meta)\n        if (\n            root_tt_depth < TT_QDEPTH_BASE\n            and root_tt_depth >= depth\n            and _tt_meta_flag(root_meta) == TT_EXACT\n        ):\n            return int(preferred), int(_tt_meta_score(root_meta, 0)), False\n    _order_moves(board, moves, count, preferred, score_stack[0])\n'''
if s.count(old)!=1:
    raise SystemExit(f'root TT anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
