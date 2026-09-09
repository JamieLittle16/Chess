#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
cap = int(sys.argv[2])
if cap not in (4, 6, 8):
    raise SystemExit(cap)
s = p.read_text()


def one(old: str, new: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor {n}: {old[:120]!r}")
    s = s.replace(old, new, 1)


one(
    "TT_QDEPTH_BASE = 64\nTT_NO_MOVE = TT_MOVE_MASK\n",
    f"TT_QDEPTH_BASE = 64\nQTT_ACTIVE_MAX_QPLY = {cap}\nTT_NO_MOVE = TT_MOVE_MASK\n",
)

# Scope the store edit to the qsearch TT store function so identical TT snippets
# elsewhere in the search cannot create ambiguous anchors.
store_start = s.index("def _qsearch_tt_store(")
store_end = s.index("\ndef _quiescence(", store_start)
store = s[store_start:store_end]
old_store = """    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n"""
if store.count(old_store) != 1:
    raise SystemExit(f"qstore anchor {store.count(old_store)}")
store = store.replace(
    old_store,
    """    if q_depth < TT_QDEPTH_BASE + max(0, MAX_QPLY - QTT_ACTIVE_MAX_QPLY):\n        return\n    tt_index = _tt_index(current_key, current_tt_context)\n    old_meta = tt_table[TT_META_OFFSET + tt_index]\n""",
    1,
)
s = s[:store_start] + store + s[store_end:]

# Scope the probe edit to _quiescence; the full search has a deliberately similar
# TT-match block which must remain untouched.
q_start = s.index("def _quiescence(")
q_end = s.index("\ndef _negamax(", q_start)
q = s[q_start:q_end]
old_probe = """    tt_match = (\n        tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context\n        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)\n    )\n    meta = tt_table[TT_META_OFFSET + tt_index] if tt_match else np.uint64(0)\n"""
if q.count(old_probe) != 1:
    raise SystemExit(f"qprobe anchor {q.count(old_probe)}")
q = q.replace(
    old_probe,
    """    tt_match = (\n        qply <= QTT_ACTIVE_MAX_QPLY\n        and tt_table[TT_KEYS_OFFSET + tt_index] == current_key\n        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context\n        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)\n    )\n    meta = tt_table[TT_META_OFFSET + tt_index] if tt_match else np.uint64(0)\n""",
    1,
)
s = s[:q_start] + q + s[q_end:]

p.write_text(s)
print("patched qTT active max qply", cap)
