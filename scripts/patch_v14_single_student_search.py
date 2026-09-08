#!/usr/bin/env python3
"""Integrate a quantised H64 absolute768 residual student into exact V13 search.

The student is additive: scale 0 is exactly V13, and positive scales add a White-perspective neural
correction on top of current V13.  One incremental accumulator is appended to the existing eval state.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, numerator: int, denominator: int) -> None:
    if numerator < 0 or denominator <= 0:
        raise SystemExit("student scale must have numerator >= 0 and denominator > 0")
    source = path.read_text()

    source = replace_once(
        source,
        "from numba import njit\n",
        """from numba import njit

from experiments.v14_student_single_runtime import (
    advance_absolute768_accumulator_into,
    build_absolute768_accumulator_into,
    infer_absolute768_student_cp,
    trunc_div_scalar,
)
""",
        "runtime import",
    )

    source = replace_once(
        source,
        """RESIDUAL_BIAS = 61
RESIDUAL_CLAMP = 600
""",
        f"""RESIDUAL_BIAS = 61
RESIDUAL_CLAMP = 600

_student_model = np.load(Path(__file__).with_name("v14_student_h64.npz"), allow_pickle=False)
STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_OUTPUT_BIAS = int(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
    raise ValueError("invalid V14 H64 student feature matrix")
if STUDENT_FEATURE_BIAS.shape != (64,) or STUDENT_OUTPUT_WEIGHTS.shape != (64,):
    raise ValueError("invalid V14 H64 student head")
STUDENT_SCALE_NUM = {numerator}
STUDENT_SCALE_DEN = {denominator}
""",
        "student model globals",
    )

    source = replace_once(
        source,
        """EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_WIDTH = 8
""",
        """EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_V13_WIDTH = 8
STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
EVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN
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
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:EVAL_WIDTH],
    )


@njit(cache=False, inline="always")
def _evaluate_state_classical""",
        "root accumulator build",
    )

    source = replace_once(
        source,
        """    correction = correction // 6
    return score + correction
""",
        """    correction = correction // 6
    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
    if side != WHITE:
        student_cp = -student_cp
    student_cp = trunc_div_scalar(student_cp * STUDENT_SCALE_NUM, STUDENT_SCALE_DEN)
    return score + correction + student_cp
""",
        "student inference",
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
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )

@njit(cache=False, inline="always")
def _repetition_piece_index""",
        "incremental accumulator update",
    )

    for marker in (
        "STUDENT_FEATURE_WEIGHTS",
        "STUDENT_SCALE_NUM",
        "infer_absolute768_student_cp",
        "advance_absolute768_accumulator_into",
    ):
        if marker not in source:
            raise SystemExit(f"missing marker after patch: {marker}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--numerator", type=int, required=True)
    parser.add_argument("--denominator", type=int, required=True)
    args = parser.parse_args()
    patch(args.path, args.numerator, args.denominator)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
