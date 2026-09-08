#!/usr/bin/env python3
"""Store the complete V14 per-ply eval stack as int16 instead of int32.

Conservative legal-position bounds are safely inside int16:
- phase/counts/king squares: <64;
- classical base: <15,000cp for one side's maximum legal promoted material;
- V13 residual: <=32*194 < 6,300 from the frozen weight extrema;
- H64 student accumulator: <= max|bias| + 32*max|feature weight| < 1,200.

All arithmetic already converts entries to Python/Numba ints before scoring; this patch changes only
storage width. Qualification requires rebuild equality and exact fixed-node search signatures.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def patch(path: Path) -> None:
    source = path.read_text()
    old = "eval_stack = np.empty((MAX_PLY, EVAL_WIDTH), dtype=np.int32)"
    count = source.count(old)
    if count != 3:
        raise SystemExit(f"expected 3 eval-stack allocations, found {count}")
    source = source.replace(old, "eval_stack = np.empty((MAX_PLY, EVAL_WIDTH), dtype=np.int16)")
    if source.count("dtype=np.int16") < 3:
        raise SystemExit("int16 eval-stack patch failed")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
