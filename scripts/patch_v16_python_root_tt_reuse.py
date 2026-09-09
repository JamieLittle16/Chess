#!/usr/bin/env python3
"""Reuse sufficiently deep exact persistent-TT entries at the real search root.

V14 already preserves its full TT across moves and guards entries by exact position key, reversible-
history fingerprint and halfmove state. Descendants from the previous move's search can therefore
become the next real root with a valid exact score. Rust V15 consumes such exact root entries;
Python currently uses them only as move-ordering hints and needlessly repeats already-proven early
iterative depths.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("path", type=Path)
    a = p.parse_args()
    text = a.path.read_text()
    old = """    if (\n        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key\n        and tt_table[TT_CONTEXTS_OFFSET + root_tt_index] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n    _order_moves(board, moves, count, preferred, score_stack[0])\n"""
    new = """    if (\n        tt_table[TT_KEYS_OFFSET + root_tt_index] == root_key\n        and tt_table[TT_CONTEXTS_OFFSET + root_tt_index] == root_tt_context\n        and root_meta != np.uint64(0)\n    ):\n        preferred = _tt_meta_move(root_meta)\n        # The persistent TT identity includes the exact reversible-history fingerprint and\n        # halfmove clock, while mate scores are stored root-ply-normalised. If this position was\n        # searched as a descendant on the preceding move, an exact sufficiently deep entry is\n        # therefore valid at the new real root. Skip redundant early iterative depths exactly as\n        # the Rust V15 root search does.\n        if _tt_meta_depth(root_meta) >= depth and _tt_meta_flag(root_meta) == TT_EXACT:\n            return int(preferred), int(_tt_meta_score(root_meta, 0)), False\n    _order_moves(board, moves, count, preferred, score_stack[0])\n"""
    if text.count(old) != 1:
        raise SystemExit(f"root TT anchor count={text.count(old)}")
    a.path.write_text(text.replace(old, new, 1))
    print("patched exact persistent-TT reuse at root")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
