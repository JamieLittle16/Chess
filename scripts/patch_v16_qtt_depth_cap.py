#!/usr/bin/env python3
from pathlib import Path
import sys

p=Path(sys.argv[1])
cap=int(sys.argv[2])
if cap not in (4,6,8):
    raise SystemExit(cap)
s=p.read_text()

def one(old,new):
    global s
    n=s.count(old)
    if n!=1:
        raise SystemExit(f'anchor {n}: {old[:100]!r}')
    s=s.replace(old,new,1)

one(
    'TT_QDEPTH_BASE = 64\nTT_NO_MOVE = TT_MOVE_MASK\n',
    f'TT_QDEPTH_BASE = 64\nQTT_ACTIVE_MAX_QPLY = {cap}\nTT_NO_MOVE = TT_MOVE_MASK\n',
)
one(
    '''    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n''',
    '''    if q_depth < TT_QDEPTH_BASE + max(0, MAX_QPLY - QTT_ACTIVE_MAX_QPLY):\n        return\n    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n''',
)
one(
    '''    tt_index = _tt_index(current_key, current_tt_context)\n    tt_match = (\n        tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n''',
    '''    tt_index = _tt_index(current_key, current_tt_context)\n    q_depth = TT_QDEPTH_BASE + max(0, MAX_QPLY - qply)\n    tt_match = (\n        qply <= QTT_ACTIVE_MAX_QPLY\n        and tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n''',
)
one(
    '''    tt_preferred = _tt_meta_move(meta) if tt_match else -1\n    q_depth = TT_QDEPTH_BASE + max(0, MAX_QPLY - qply)\n    if tt_match:\n''',
    '''    tt_preferred = _tt_meta_move(meta) if tt_match else -1\n    if tt_match:\n''',
)
p.write_text(s)
print('patched qTT active max qply',cap)
