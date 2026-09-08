#!/usr/bin/env python3
"""Maintain one absolute768 NNUE accumulator through exact V13 search without using its score."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, hidden: int) -> None:
    if hidden not in (32, 48, 64, 96, 128):
        raise SystemExit(f"unsupported shadow hidden width: {hidden}")
    source = path.read_text()
    source = replace_once(
        source,
        "from numba import njit\n",
        """from numba import njit

from experiments.v14_nnue_single_runtime import (
    advance_absolute768_accumulator_into,
    build_absolute768_accumulator_into,
)
""",
        "runtime import",
    )
    source = replace_once(
        source,
        """EVAL_RESIDUAL_BLACK = 7
EVAL_WIDTH = 8
""",
        f"""EVAL_RESIDUAL_BLACK = 7
EVAL_V13_WIDTH = 8
SHADOW_HIDDEN = {hidden}
SHADOW_OFFSET = EVAL_V13_WIDTH
EVAL_WIDTH = EVAL_V13_WIDTH + SHADOW_HIDDEN
_shadow_ids = np.arange(768 * SHADOW_HIDDEN, dtype=np.int32).reshape(768, SHADOW_HIDDEN)
SHADOW_FEATURE_WEIGHTS = (((_shadow_ids * 37 + 11) % 31) - 15).astype(np.int16)
SHADOW_FEATURE_BIAS = (((np.arange(SHADOW_HIDDEN, dtype=np.int32) * 13 + 7) % 17) - 8).astype(np.int16)
del _shadow_ids
""",
        "eval width",
    )
    source = replace_once(
        source,
        """    state[EVAL_RESIDUAL_WHITE] = white_residual
    state[EVAL_RESIDUAL_BLACK] = black_residual


@njit(cache=False, inline="always")
def _evaluate_state_classical""",
        """    state[EVAL_RESIDUAL_WHITE] = white_residual
    state[EVAL_RESIDUAL_BLACK] = black_residual
    build_absolute768_accumulator_into(
        board,
        SHADOW_FEATURE_WEIGHTS,
        SHADOW_FEATURE_BIAS,
        state[SHADOW_OFFSET:EVAL_WIDTH],
    )


@njit(cache=False, inline="always")
def _evaluate_state_classical""",
        "root accumulator build",
    )
    source = replace_once(
        source,
        """    _advance_residual_state_into(board, side, move, parent, child)

@njit(cache=False, inline="always")
def _repetition_piece_index""",
        """    _advance_residual_state_into(board, side, move, parent, child)
    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[SHADOW_OFFSET:EVAL_WIDTH],
        child[SHADOW_OFFSET:EVAL_WIDTH],
        SHADOW_FEATURE_WEIGHTS,
    )

@njit(cache=False, inline="always")
def _repetition_piece_index""",
        "incremental accumulator update",
    )
    if source.count("SHADOW_FEATURE_WEIGHTS") != 4:
        raise SystemExit("single-shadow integration structure drifted")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--hidden", type=int, required=True)
    args = parser.parse_args()
    patch(args.path, args.hidden)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
