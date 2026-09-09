#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
cap = int(sys.argv[2])
if cap not in (4, 6, 8):
    raise SystemExit(f"unsupported cap: {cap}")
s = p.read_text()

def one(old: str, new: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor count {n}: {old[:120]!r}")
    s = s.replace(old, new, 1)

one(
    "TT_QDEPTH_BASE = 64\nTT_NO_MOVE = TT_MOVE_MASK\n",
    f"TT_QDEPTH_BASE = 64\nQTT_ACTIVE_MAX_QPLY = {cap}\nTT_NO_MOVE = TT_MOVE_MASK\n",
)
one(
    """    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n""",
    """    if q_depth < TT_QDEPTH_BASE + max(0, MAX_QPLY - QTT_ACTIVE_MAX_QPLY):\n        return\n    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n""",
)
one(
    """    tt_match = (\n        tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context\n        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)\n    )\n""",
    """    tt_match = (\n        qply <= QTT_ACTIVE_MAX_QPLY\n        and tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context\n        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)\n    )\n""",
)
p.write_text(s)
print(f"patched qTT active max qply = {cap}")
