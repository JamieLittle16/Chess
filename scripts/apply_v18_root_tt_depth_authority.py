#!/usr/bin/env python3
"""Use inherited root-TT move only while it is deeper than the current root iteration."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()
    old = """    if (\n        tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_KEYS_OFFSET] == root_key\n        and tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_CONTEXTS_OFFSET] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n"""
    new = """    # V18 ROOT-TT-DEPTH: this root TT record is inherited from an earlier game ply;\n    # `_root` itself does not store root entries.  Preserve that useful future-node hint while\n    # it represents at least as deep a search as the iteration we are about to run.  Once current\n    # iterative deepening catches up, the explicit `preferred` argument is the fresher PV from\n    # this exact root and should get PVS's full-window first slot.\n    root_tt_match = (\n        tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_KEYS_OFFSET] == root_key\n        and tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_CONTEXTS_OFFSET] == root_tt_context\n        and root_meta != np.uint64(0)\n    )\n    if root_tt_match and _tt_meta_depth(root_meta) >= depth:\n        preferred = _tt_meta_move(root_meta)\n"""
    if s.count(old) != 1:
        raise RuntimeError(f"root TT authority anchor count {s.count(old)}, expected 1")
    p.write_text(s.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
