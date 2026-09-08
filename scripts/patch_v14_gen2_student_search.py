#!/usr/bin/env python3
"""Integrate a generation-2 absolute768 student into exact V13 search.

Two deployment modes are supported:

* additive: classical + qualified V13 residual/6 + scaled student;
* replacement: classical + scaled student, skipping V13 residual transport at searched moves.

Both modes use the student at ordinary alpha-beta nodes and at qsearch entry only. Deeper qsearch
falls back to the corresponding cheap baseline and transports only the state prefix it needs.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, *, hidden: int, numerator: int, denominator: int, mode: str) -> None:
    if hidden not in (64, 96, 128):
        raise SystemExit("hidden must be 64, 96, or 128")
    if numerator < 0 or denominator <= 0:
        raise SystemExit("student scale must have numerator >= 0 and denominator > 0")
    if mode not in ("additive", "replacement"):
        raise SystemExit("mode must be additive or replacement")
    source = path.read_text()
    if "STUDENT_GEN2_MODE_REPLACEMENT" in source:
        raise SystemExit("generation-2 student patch already applied")

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

_student_model = np.load(Path(__file__).with_name("v14_student_model.npz"), allow_pickle=False)
STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_OUTPUT_BIAS = int(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, {hidden}):
    raise ValueError("invalid V14 generation-2 student feature matrix")
if STUDENT_FEATURE_BIAS.shape != ({hidden},) or STUDENT_OUTPUT_WEIGHTS.shape != ({hidden},):
    raise ValueError("invalid V14 generation-2 student head")
STUDENT_SCALE_NUM = {numerator}
STUDENT_SCALE_DEN = {denominator}
STUDENT_GEN2_MODE_REPLACEMENT = {1 if mode == 'replacement' else 0}
""",
        "student model globals",
    )

    source = replace_once(
        source,
        """EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_WIDTH = 8
""",
        f"""EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_CLASSICAL_WIDTH = 6
EVAL_V13_WIDTH = 8
STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = {hidden}
EVAL_WIDTH = STUDENT_OFFSET + STUDENT_HIDDEN
QSEARCH_EVAL_WIDTH = EVAL_CLASSICAL_WIDTH if STUDENT_GEN2_MODE_REPLACEMENT else EVAL_V13_WIDTH
""",
        "eval width",
    )

    old_build = """    state[EVAL_RESIDUAL_WHITE] = white_residual
    state[EVAL_RESIDUAL_BLACK] = black_residual


@njit(cache=False, inline="always")
def _evaluate_state_classical"""
    if mode == "additive":
        residual_store = """    state[EVAL_RESIDUAL_WHITE] = white_residual
    state[EVAL_RESIDUAL_BLACK] = black_residual
"""
    else:
        residual_store = """    # Replacement mode deliberately makes the legacy residual cells inert. Keeping them
    # deterministic gives us exact full-refresh/incremental state parity without paying its lookup path.
    state[EVAL_RESIDUAL_WHITE] = 0
    state[EVAL_RESIDUAL_BLACK] = 0
"""
    new_build = residual_store + """    build_absolute768_accumulator_into(
        board,
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:EVAL_WIDTH],
    )


@njit(cache=False, inline="always")
def _evaluate_state_classical"""
    source = replace_once(source, old_build, new_build, "root accumulator build")

    old_eval = """    correction = correction // 6
    return score + correction
"""
    if mode == "additive":
        new_eval = """    correction = correction // 6
    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
    if side != WHITE:
        student_cp = -student_cp
    student_cp = trunc_div_scalar(student_cp * STUDENT_SCALE_NUM, STUDENT_SCALE_DEN)
    return score + correction + student_cp
"""
    else:
        new_eval = """    # Replacement student is trained directly against the classical baseline.
    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
    if side != WHITE:
        student_cp = -student_cp
    student_cp = trunc_div_scalar(student_cp * STUDENT_SCALE_NUM, STUDENT_SCALE_DEN)
    return score + student_cp
"""
    source = replace_once(source, old_eval, new_eval, "student inference")

    eval_anchor = new_eval + "\n\n@njit(cache=False, inline=\"never\")\ndef _advance_residual_state_into("
    v13_helper = new_eval + '''


@njit(cache=False, inline="always")
def _evaluate_state_v13_only(side: int, state: np.ndarray) -> int:
    # Exact qualified V13 evaluation, ignoring appended student cells.
    score = _evaluate_state_classical(side, state)
    if side == WHITE:
        correction = int(state[EVAL_RESIDUAL_WHITE]) - int(state[EVAL_RESIDUAL_BLACK])
    else:
        correction = int(state[EVAL_RESIDUAL_BLACK]) - int(state[EVAL_RESIDUAL_WHITE])
    correction += RESIDUAL_BIAS
    if RESIDUAL_CLAMP > 0:
        if correction > RESIDUAL_CLAMP:
            correction = RESIDUAL_CLAMP
        elif correction < -RESIDUAL_CLAMP:
            correction = -RESIDUAL_CLAMP
    correction = correction // 6
    return score + correction


@njit(cache=False, inline="never")
def _advance_residual_state_into('''
    source = replace_once(source, eval_anchor, v13_helper, "V13-only evaluator insertion")

    source = replace_once(
        source,
        """    _advance_residual_state_into(board, side, move, parent, child)

@njit(cache=False, inline="always")
def _repetition_piece_index""",
        """    # Short state slices are used below qsearch entry. Replacement mode deliberately skips
    # the legacy residual weight lookups on normal searched moves.
    if parent.shape[0] >= EVAL_V13_WIDTH:
        if STUDENT_GEN2_MODE_REPLACEMENT:
            child[EVAL_RESIDUAL_WHITE] = 0
            child[EVAL_RESIDUAL_BLACK] = 0
        else:
            _advance_residual_state_into(board, side, move, parent, child)
    if parent.shape[0] >= EVAL_WIDTH:
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
        "incremental transport",
    )

    source = replace_once(
        source,
        """        stand_pat = _evaluate_state(side, eval_stack[ply])
""",
        """        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        elif STUDENT_GEN2_MODE_REPLACEMENT:
            stand_pat = _evaluate_state_classical(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
""",
        "qsearch stand-pat",
    )

    source = replace_once(
        source,
        """    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
""",
        """    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :QSEARCH_EVAL_WIDTH],
            eval_stack[ply + 1, :QSEARCH_EVAL_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
""",
        "qsearch incremental state",
    )

    for marker in (
        "STUDENT_GEN2_MODE_REPLACEMENT",
        "QSEARCH_EVAL_WIDTH",
        "advance_absolute768_accumulator_into",
        "_evaluate_state_v13_only",
    ):
        if marker not in source:
            raise SystemExit(f"missing marker after patch: {marker}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--hidden", type=int, required=True)
    parser.add_argument("--numerator", type=int, required=True)
    parser.add_argument("--denominator", type=int, required=True)
    parser.add_argument("--mode", choices=("additive", "replacement"), required=True)
    args = parser.parse_args()
    patch(args.path, hidden=args.hidden, numerator=args.numerator, denominator=args.denominator, mode=args.mode)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
