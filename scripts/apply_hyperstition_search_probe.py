#!/usr/bin/env python3
"""Swap the accepted Gestalt leaf evaluator for Hyperstition in a qualification checkout.

The production search semantics are intentionally unchanged. This patch only substitutes the
incremental evaluator state and environment-selected network; RFP/futility, move ordering, qsearch,
LMR and all other search decisions continue to use the same call sites and logic.
"""

from __future__ import annotations

import re
from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new)


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    required = [
        "GestaltSearchEvaluator",
        "GestaltAccumulatorState",
        "GestaltNetwork",
        "GestaltPreparedUpdate",
        "CHESS_GESTALT_NETWORK",
        "gestalt",
    ]
    for token in required:
        if token not in text:
            raise PatchError(f"expected production Gestalt token missing: {token}")

    text = text.replace("GestaltSearchEvaluator", "HyperstitionSearchEvaluator")
    text = text.replace("GestaltAccumulatorState", "HyperstitionAccumulatorState")
    text = text.replace("GestaltNetwork", "HyperstitionNetwork")
    text = text.replace("GestaltPreparedUpdate", "HyperstitionPreparedUpdate")
    text = text.replace("CHESS_GESTALT_NETWORK", "CHESS_HYPERSTITION_NETWORK")
    text = re.sub(r"\bgestalt\b", "hyperstition", text)

    text = replace_exact(
        text,
        "return accumulator.evaluate(&hyperstition.network, position.side_to_move());",
        "return accumulator.evaluate(&hyperstition.network, position);",
        count=1,
        label="Hyperstition position-aware evaluation call",
    )

    stale = [
        "GestaltSearchEvaluator",
        "GestaltAccumulatorState",
        "GestaltNetwork",
        "GestaltPreparedUpdate",
        "CHESS_GESTALT_NETWORK",
        "gestalt",
    ]
    leftovers = [token for token in stale if token in text]
    if leftovers:
        raise PatchError(f"stale Gestalt integration tokens remain: {leftovers}")

    if text.count("CHESS_HYPERSTITION_NETWORK") != 2:
        raise PatchError(
            "expected CHESS_HYPERSTITION_NETWORK in lookup and load-error message exactly twice"
        )
    if text.count("HyperstitionAccumulatorState::prepare_move") != 1:
        raise PatchError("expected exactly one Hyperstition prepare_move integration call")
    if text.count(".apply_prepared(&hyperstition.network, position, prepared)") != 1:
        raise PatchError("expected exactly one Hyperstition apply_prepared integration call")
    if text.count(".restore_after_unmake(&hyperstition.network, position, prepared)") != 1:
        raise PatchError("expected exactly one Hyperstition restore integration call")

    path.write_text(text, encoding="utf-8")
    print("applied Hyperstition evaluator substitution; search semantics otherwise unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
