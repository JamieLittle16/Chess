#!/usr/bin/env python3
"""Integrate H64 absolute768 residual student with an incrementally cached output sum.

The student is exactly the qualified 1/12 model. One H64 accumulator plus one raw SCReLU/output
sum is appended to V13 state. The raw sum is updated in the same neuron pass as the accumulator, so
later neural evaluation is O(1) scaling rather than another H64 walk.
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
    advance_absolute768_accumulator_and_raw_into,
    build_absolute768_accumulator_into,
    raw_absolute768_student_cp,
    raw_screlu_output_sum,
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
STUDENT_ACC_END = STUDENT_OFFSET + STUDENT_HIDDEN
STUDENT_RAW = STUDENT_ACC_END
EVAL_WIDTH = STUDENT_RAW + 1
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
        state[STUDENT_OFFSET:STUDENT_ACC_END],
    )
    state[STUDENT_RAW] = raw_screlu_output_sum(
        state[STUDENT_OFFSET:STUDENT_ACC_END],
        STUDENT_OUTPUT_WEIGHTS,
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
    student_cp = raw_absolute768_student_cp(
        int(state[STUDENT_RAW]),
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
    if parent.shape[0] >= EVAL_WIDTH:
        child[STUDENT_RAW] = advance_absolute768_accumulator_and_raw_into(
            board,
            side,
            move,
            parent[STUDENT_OFFSET:STUDENT_ACC_END],
            child[STUDENT_OFFSET:STUDENT_ACC_END],
            STUDENT_FEATURE_WEIGHTS,
            STUDENT_OUTPUT_WEIGHTS,
            int(parent[STUDENT_RAW]),
        )

@njit(cache=False, inline="always")
def _repetition_piece_index""",
        "incremental accumulator/raw update",
    )

    for marker in (
        "STUDENT_RAW",
        "raw_absolute768_student_cp",
        "advance_absolute768_accumulator_and_raw_into",
        "raw_screlu_output_sum",
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
