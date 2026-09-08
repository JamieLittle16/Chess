#!/usr/bin/env python3
"""Disable shallow reverse/late futility after History-v2 materialization.

This isolates whether v14's large learned-pruning gain comes from a better Gestalt pruning oracle or
from removing harmful classical-oracle cutoffs after the evaluator transition.
"""

from pathlib import Path


class PatchError(RuntimeError):
    pass


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    old = """        let pruning_eligible = depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position);
"""
    new = """        // v14 ablation: disable the shallow static-eval pruning family entirely.
        // This preserves the rest of Search-v2 while testing whether the old pruning policy itself,
        // rather than merely its classical oracle, became harmful after the Gestalt transition.
        let pruning_eligible = false;
"""
    if text.count(old) != 1:
        raise PatchError(f"pruning eligibility: expected 1 occurrence, found {text.count(old)}")
    text = text.replace(old, new, 1)

    old_fn = "fn has_reverse_futility_material(position: &Position) -> bool {\n"
    new_fn = "#[allow(dead_code)]\nfn has_reverse_futility_material(position: &Position) -> bool {\n"
    if text.count(old_fn) != 1:
        raise PatchError(f"RFP material helper: expected 1 occurrence, found {text.count(old_fn)}")
    text = text.replace(old_fn, new_fn, 1)

    path.write_text(text, encoding="utf-8")
    print("applied v14 no-shallow-futility ablation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
