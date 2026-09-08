#!/usr/bin/env python3
"""Port Rust production TT identity into exact packaged Python V14.

Rule draws remain checked before every TT probe. The TT itself is keyed only by the board Zobrist,
matching Rust V15, instead of mixing reversible-history and halfmove-clock context into identity.
This also removes the dedicated context array and per-child history-context hashing from the hot path.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_rust_tt_parity.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''TT_KEYS_OFFSET = 0
TT_CONTEXTS_OFFSET = TT_SIZE
TT_META_OFFSET = TT_SIZE * 2
TT_GENERATION_INDEX = TT_SIZE * 3
TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1
'''
new = '''TT_KEYS_OFFSET = 0
TT_META_OFFSET = TT_SIZE
TT_GENERATION_INDEX = TT_SIZE * 2
TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1
'''
if s.count(old) != 1: raise SystemExit(f"TT layout anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''@njit(cache=False, inline="always")
def _tt_index(position: np.uint64, context_identity: np.uint64) -> int:
    return int((position ^ context_identity) & np.uint64(TT_MASK))
'''
new = '''@njit(cache=False, inline="always")
def _tt_index(position: np.uint64) -> int:
    return int(position & np.uint64(TT_MASK))
'''
if s.count(old) != 1: raise SystemExit(f"TT index anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    current_key = path_keys[ply]
    current_context = history_contexts[ply]
    current_tt_context = _tt_context_identity(current_context, halfmove_clock)
    tt_index = _tt_index(current_key, current_tt_context)
    tt_match = (
        tt_table[TT_KEYS_OFFSET + tt_index] == current_key
        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context
        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)
    )
'''
new = '''    current_key = path_keys[ply]
    tt_index = _tt_index(current_key)
    tt_match = (
        tt_table[TT_KEYS_OFFSET + tt_index] == current_key
        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)
    )
'''
if s.count(old) != 1: raise SystemExit(f"negamax TT probe anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )
'''
new = '''        history_contexts[ply + 1] = np.uint64(0)
'''
if s.count(old) != 1: raise SystemExit(f"child context anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        same_tt_entry = (
            tt_table[TT_KEYS_OFFSET + tt_index] == current_key
            and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context
            and old_meta != np.uint64(0)
        )
'''
new = '''        same_tt_entry = (
            tt_table[TT_KEYS_OFFSET + tt_index] == current_key
            and old_meta != np.uint64(0)
        )
'''
if s.count(old) != 1: raise SystemExit(f"TT replacement anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''            tt_table[TT_KEYS_OFFSET + tt_index] = current_key
            tt_table[TT_CONTEXTS_OFFSET + tt_index] = current_tt_context
            tt_table[TT_META_OFFSET + tt_index] = _tt_pack_meta(
'''
new = '''            tt_table[TT_KEYS_OFFSET + tt_index] = current_key
            tt_table[TT_META_OFFSET + tt_index] = _tt_pack_meta(
'''
if s.count(old) != 1: raise SystemExit(f"TT store anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    root_key = path_keys[0]
    root_context = history_contexts[0]
    root_tt_context = _tt_context_identity(root_context, halfmove_clock)
    root_tt_index = _tt_index(root_key, root_tt_context)
    root_meta = tt_table[TT_META_OFFSET + root_tt_index]
    if (
        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key
        and tt_table[TT_CONTEXTS_OFFSET + root_tt_index] == root_tt_context
        and root_meta != np.uint64(0)
    ):
'''
new = '''    root_key = path_keys[0]
    root_tt_index = _tt_index(root_key)
    root_meta = tt_table[TT_META_OFFSET + root_tt_index]
    if (
        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key
        and root_meta != np.uint64(0)
    ):
'''
if s.count(old) != 1: raise SystemExit(f"root TT probe anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        history_contexts[1] = _child_history_context(
            root_context, root_key, child_halfmove
        )
'''
new = '''        history_contexts[1] = np.uint64(0)
'''
if s.count(old) != 1: raise SystemExit(f"root child context anchor count={s.count(old)}")
s = s.replace(old, new, 1)

count = s.count('history_contexts[0] = _root_history_context(history_keys, history_count)')
if count < 1: raise SystemExit('root history-context initialization anchor missing')
s = s.replace('history_contexts[0] = _root_history_context(history_keys, history_count)', 'history_contexts[0] = np.uint64(0)')

if 'TT_CONTEXTS_OFFSET' in s: raise SystemExit('live TT_CONTEXTS_OFFSET remains')
if '_tt_index(current_key,' in s or '_tt_index(root_key,' in s: raise SystemExit('two-argument TT index call remains')
p.write_text(s)
