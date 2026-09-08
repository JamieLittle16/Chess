#!/usr/bin/env python3
"""Make shallow futility pruning use the active leaf evaluator.

This patch is intended to be applied after `apply_history_v2_probe.py --variant history-lmr`.
Production currently uses the mature Gestalt evaluator at ordinary leaves and qsearch stand pat, but
reverse/late futility derives its static cutoff score from the old classical evaluator. This probe
asks whether aligning those pruning decisions with the mature evaluator gains enough search quality
to justify the extra output-head work at the small subset of eligible shallow scout nodes.
"""

from pathlib import Path


class PatchError(RuntimeError):
    pass


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    old = """            Some(evaluate(position))
        } else {
            None
        };
"""
    new = """            Some(self.leaf_evaluate(position))
        } else {
            None
        };
"""
    count = text.count(old)
    if count != 1:
        raise PatchError(f"learned pruning static eval: expected 1 occurrence, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("applied v14 learned shallow-pruning static evaluation")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
