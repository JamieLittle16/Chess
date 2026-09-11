#!/usr/bin/env python3
"""Apply conservative root-preference authority experiments to extracted PUNCH133."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--mode", choices=("pv_after1", "no_root_tt"), required=True)
    args = ap.parse_args()

    p = args.path
    s = p.read_text()
    old = """    if (\n        tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_KEYS_OFFSET] == root_key\n        and tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_CONTEXTS_OFFSET] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n"""
    if s.count(old) != 1:
        raise RuntimeError(f"root TT preference anchor count is {s.count(old)}, expected 1")

    if args.mode == "pv_after1":
        new = """    # V18 candidate: a root TT move is valuable on the first iteration because it may\n    # come from the previous game ply.  Once depth 1 completes, however, the explicit\n    # `preferred` argument is the fresher PV from this very root and must win.  PVS gives\n    # the first move the full window, so allowing an older TT move to clobber that PV wastes\n    # the most expensive root slot on every later iteration.\n    if depth == 1 and (\n        tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_KEYS_OFFSET] == root_key\n        and tt_table[root_tt_index * TT_ENTRY_STRIDE + TT_CONTEXTS_OFFSET] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n"""
    else:
        new = """    # V18 ablation: the caller's explicit root preference always wins.  This tests\n    # whether even the first-iteration root TT hint is inferior to the freshly computed\n    # fallback/book preference.\n"""

    p.write_text(s.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
