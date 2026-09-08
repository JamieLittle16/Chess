#!/usr/bin/env python3
"""Replace classical-only shallow pruning eval with an already-maintained learned state.

Modes:
- v13: use the incremental V13 residual evaluation (near-zero extra arithmetic);
- h64: use the exact packaged V14 H64 blended evaluation.

Only the RFP / late-quiet-futility static bound changes. Search, move ordering, LMR, qsearch,
TT semantics, time management and the evaluation returned at ordinary leaves remain untouched.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("v13", "h64"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    source = args.path.read_text()
    old = "        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])\n"
    fn = "_evaluate_state_v13_only" if args.mode == "v13" else "_evaluate_state"
    new = f"        pruning_static_eval = {fn}(side, eval_stack[ply])\n"
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"expected one classical pruning eval site, found {count}")
    source = source.replace(old, new, 1)
    if source.count(new) != 1:
        raise SystemExit("replacement did not materialize exactly once")
    args.path.write_text(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
