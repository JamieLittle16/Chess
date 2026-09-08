#!/usr/bin/env python3
"""Patch exact V13 with one-ply internal iterative reduction variants.

IIR is deliberately simple: after TT/hash move lookup, a sufficiently deep non-check node without
any preferred move may search one ply shallower.  The move set, evaluation, draw rules and TT
identity remain unchanged.  Variants explore conservative scout-only vs all-window gating.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, variant: str) -> None:
    conditions = {
        "i1": "depth >= 6 and preferred < 0 and not checked and beta == alpha + 1",
        "i2": "depth >= 6 and preferred < 0 and not checked",
        "i3": "depth >= 5 and preferred < 0 and not checked and beta == alpha + 1",
        "i4": "depth >= 7 and preferred < 0 and not checked",
    }
    if variant not in conditions:
        raise SystemExit("variant must be one of i1,i2,i3,i4")
    source = path.read_text()
    old = """    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))
    hash_preferred = int(hash_moves[hash_index]) if hash_keys[hash_index] == current_key else -1
    preferred = tt_preferred if tt_preferred >= 0 else hash_preferred
    _order_moves_with_killers(
"""
    new = f"""    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))
    hash_preferred = int(hash_moves[hash_index]) if hash_keys[hash_index] == current_key else -1
    preferred = tt_preferred if tt_preferred >= 0 else hash_preferred

    # V14 IIR-A: a node with no transposition/hash move has weaker move-order information.  At
    # sufficient depth spend one less nominal ply here and let iterative deepening/verification
    # recover it where the line matters.  This mirrors the modern IIR principle without adding a
    # recursive pre-search or any new state.
    if {conditions[variant]}:
        depth -= 1

    _order_moves_with_killers(
"""
    source = replace_once(source, old, new, "IIR insertion")
    if "depth -= 1" not in source or "V14 IIR-A" not in source:
        raise SystemExit("IIR markers missing after patch")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--variant", choices=("i1", "i2", "i3", "i4"), required=True)
    args = parser.parse_args()
    patch(args.path, args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
