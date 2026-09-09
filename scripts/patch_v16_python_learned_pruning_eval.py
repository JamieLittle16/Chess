#!/usr/bin/env python3
"""Use the real learned leaf evaluator for RFP/futility pruning decisions.

Rust V15's accepted RFP/late-quiet-futility stack derives its shared pruning static
score from `leaf_evaluate`.  Packaged Python V14 still uses the classical-only
component even though its H64/V13 learned state is already incrementally available.
This patch changes only that evaluator source; all pruning eligibility gates,
margins, move classification and verification semantics remain unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD = "        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])\n"
NEW = "        pruning_static_eval = _evaluate_state(side, eval_stack[ply])\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    text = args.path.read_text()
    count = text.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one classical pruning-eval site, found {count}")
    text = text.replace(OLD, NEW)
    args.path.write_text(text)
    print("patched RFP/late-quiet futility to use full learned static evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
