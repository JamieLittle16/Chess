#!/usr/bin/env python3
"""Cache the H64 student's exact raw SCReLU/output sum in the per-ply eval state.

Apply after single-student integration + lean-qsearch. The neural accumulator remains exact, but each
normal move update also updates one cached int32 raw output sum in the same 64-neuron pass. Static
student inference then becomes O(1) integer scaling rather than another H64 loop.

Below qply 0 the lean-qsearch path passes an 8-cell V13-only state slice; the patched advance helper
recognises that shape and performs no neural work at all.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()
    if "STUDENT_RAW_INDEX" in source:
        raise SystemExit("cached-output patch already applied")
    if "STUDENT_HIDDEN = 64" not in source or "_evaluate_state_v13_only" not in source:
        raise SystemExit("expected integrated lean H64 student source")

    source = replace_once(
        source,
        """from experiments.v14_student_single_runtime import (
    advance_absolute768_accumulator_into,
    build_absolute768_accumulator_into,
    infer_absolute768_student_cp,
    trunc_div_scalar,
)
""",
        """from experiments.v14_student_single_runtime import (
    advance_absolute768_accumulator_and_raw_into,
    build_absolute768_accumulator_into,
    raw_absolute768_student_cp,
    raw_screlu_output_sum,
    trunc_div_scalar,
)
""",
        "runtime imports",
    )

    source = replace_once(
        source,
        """EVAL_V13_WIDTH = 8
STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
EVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN
""",
        """EVAL_V13_WIDTH = 8
STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
STUDENT_ACC_END = STUDENT_OFFSET + STUDENT_HIDDEN
STUDENT_RAW_INDEX = STUDENT_ACC_END
EVAL_WIDTH = STUDENT_RAW_INDEX + 1
""",
        "state layout",
    )

    source = replace_once(
        source,
        """    build_absolute768_accumulator_into(
        board,
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:EVAL_WIDTH],
    )
""",
        """    build_absolute768_accumulator_into(
        board,
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:STUDENT_ACC_END],
    )
    state[STUDENT_RAW_INDEX] = raw_screlu_output_sum(
        state[STUDENT_OFFSET:STUDENT_ACC_END],
        STUDENT_OUTPUT_WEIGHTS,
    )
""",
        "root cached output build",
    )

    source = replace_once(
        source,
        """    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
""",
        """    student_cp = raw_absolute768_student_cp(
        int(state[STUDENT_RAW_INDEX]),
        STUDENT_OUTPUT_BIAS,
    )
""",
        "cached inference",
    )

    source = replace_once(
        source,
        """    _advance_residual_state_into(board, side, move, parent, child)
    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )
""",
        """    _advance_residual_state_into(board, side, move, parent, child)
    if parent.shape[0] > EVAL_V13_WIDTH:
        child[STUDENT_RAW_INDEX] = advance_absolute768_accumulator_and_raw_into(
            board,
            side,
            move,
            parent[STUDENT_OFFSET:STUDENT_ACC_END],
            child[STUDENT_OFFSET:STUDENT_ACC_END],
            STUDENT_FEATURE_WEIGHTS,
            STUDENT_OUTPUT_WEIGHTS,
            int(parent[STUDENT_RAW_INDEX]),
        )
""",
        "cached incremental update",
    )

    # Lean qsearch's explicit V13-only prefix remains exactly eight cells; its comments mentioning
    # the old appended accumulator tail are still semantically correct and need no behavioural edit.
    for marker in (
        "STUDENT_RAW_INDEX",
        "raw_screlu_output_sum",
        "raw_absolute768_student_cp",
        "advance_absolute768_accumulator_and_raw_into",
    ):
        if marker not in source:
            raise SystemExit(f"missing marker after patch: {marker}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
