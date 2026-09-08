#!/usr/bin/env python3
"""Replace V13's learned residual with a king-context single-accumulator student.

The contextual student is evaluated at normal alpha-beta nodes and qsearch entry.  Deeper qsearch
uses only V13's inexpensive classical state.  The legacy residual cells are retained as deterministic
zeros to minimize invasive layout changes, but its per-move transport is removed entirely.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count=source.count(old)
    if count!=1: raise SystemExit(f'{label}: expected one anchor, found {count}')
    return source.replace(old,new,1)


def patch(path: Path, *, hidden: int, numerator: int, denominator: int) -> None:
    if hidden not in (64,96): raise SystemExit('hidden must be 64 or 96')
    if numerator < 0 or denominator <= 0: raise SystemExit('invalid scale')
    source=path.read_text()
    if 'CONTEXT_STUDENT_OFFSET' in source: raise SystemExit('context student already applied')

    source=replace_once(source,'from numba import njit\n','''from numba import njit

from experiments.v14_context_student_runtime import (
    FEATURES as CONTEXT_STUDENT_FEATURES,
    advance_context_accumulator_into,
    build_context_accumulator_into,
    infer_context_student_cp,
    king_context,
    trunc_div_scalar,
)
''','runtime import')

    source=replace_once(source,'''RESIDUAL_BIAS = 61
RESIDUAL_CLAMP = 600
''',f'''RESIDUAL_BIAS = 61
RESIDUAL_CLAMP = 600

_context_model = np.load(Path(__file__).with_name("v14_context_model.npz"), allow_pickle=False)
CONTEXT_STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_context_model["feature_weights"], dtype=np.int16)
CONTEXT_STUDENT_FEATURE_BIAS = np.ascontiguousarray(_context_model["feature_bias"], dtype=np.int16)
CONTEXT_STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_context_model["output_weights"], dtype=np.int16)
CONTEXT_STUDENT_OUTPUT_BIAS = int(np.asarray(_context_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _context_model
if CONTEXT_STUDENT_FEATURE_WEIGHTS.shape != (CONTEXT_STUDENT_FEATURES, {hidden}):
    raise ValueError("invalid V14 contextual feature matrix")
if CONTEXT_STUDENT_FEATURE_BIAS.shape != ({hidden},) or CONTEXT_STUDENT_OUTPUT_WEIGHTS.shape != ({hidden},):
    raise ValueError("invalid V14 contextual head")
CONTEXT_STUDENT_SCALE_NUM = {numerator}
CONTEXT_STUDENT_SCALE_DEN = {denominator}
''','model globals')

    source=replace_once(source,'''EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_WIDTH = 8
''',f'''EVAL_RESIDUAL_WHITE = 6
EVAL_RESIDUAL_BLACK = 7
EVAL_CLASSICAL_WIDTH = 6
EVAL_LEGACY_WIDTH = 8
EVAL_CONTEXT = 8
CONTEXT_STUDENT_OFFSET = 9
CONTEXT_STUDENT_HIDDEN = {hidden}
EVAL_WIDTH = CONTEXT_STUDENT_OFFSET + CONTEXT_STUDENT_HIDDEN
QSEARCH_EVAL_WIDTH = EVAL_CLASSICAL_WIDTH
''','eval layout')

    source=replace_once(source,'''    state[EVAL_RESIDUAL_WHITE] = white_residual
    state[EVAL_RESIDUAL_BLACK] = black_residual


@njit(cache=False, inline="always")
def _evaluate_state_classical''','''    # Contextual replacement makes legacy residual cells inert; this avoids transporting its table
    # in the hot path while preserving stable slot numbers for the classical prefix.
    state[EVAL_RESIDUAL_WHITE] = 0
    state[EVAL_RESIDUAL_BLACK] = 0
    context = king_context(int(state[EVAL_WHITE_KING]), int(state[EVAL_BLACK_KING]))
    state[EVAL_CONTEXT] = context
    build_context_accumulator_into(
        board,
        context,
        CONTEXT_STUDENT_FEATURE_WEIGHTS,
        CONTEXT_STUDENT_FEATURE_BIAS,
        state[CONTEXT_STUDENT_OFFSET:EVAL_WIDTH],
    )


@njit(cache=False, inline="always")
def _evaluate_state_classical''','root build')

    source=replace_once(source,'''    correction = correction // 6
    return score + correction
''','''    student_cp = infer_context_student_cp(
        state[CONTEXT_STUDENT_OFFSET:EVAL_WIDTH],
        CONTEXT_STUDENT_OUTPUT_WEIGHTS,
        CONTEXT_STUDENT_OUTPUT_BIAS,
    )
    if side != WHITE:
        student_cp = -student_cp
    student_cp = trunc_div_scalar(student_cp * CONTEXT_STUDENT_SCALE_NUM, CONTEXT_STUDENT_SCALE_DEN)
    return score + student_cp
''','replacement eval')

    source=replace_once(source,'''    _advance_residual_state_into(board, side, move, parent, child)

@njit(cache=False, inline="always")
def _repetition_piece_index''','''    if parent.shape[0] >= EVAL_LEGACY_WIDTH:
        child[EVAL_RESIDUAL_WHITE] = 0
        child[EVAL_RESIDUAL_BLACK] = 0
    if parent.shape[0] >= EVAL_WIDTH:
        next_context = advance_context_accumulator_into(
            board,
            side,
            move,
            int(parent[EVAL_WHITE_KING]),
            int(parent[EVAL_BLACK_KING]),
            int(parent[EVAL_CONTEXT]),
            parent[CONTEXT_STUDENT_OFFSET:EVAL_WIDTH],
            child[CONTEXT_STUDENT_OFFSET:EVAL_WIDTH],
            CONTEXT_STUDENT_FEATURE_WEIGHTS,
            CONTEXT_STUDENT_FEATURE_BIAS,
        )
        child[EVAL_CONTEXT] = next_context

@njit(cache=False, inline="always")
def _repetition_piece_index''','incremental context transport')

    source=replace_once(source,'''        stand_pat = _evaluate_state(side, eval_stack[ply])
''','''        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_classical(side, eval_stack[ply])
''','qsearch stand pat')

    source=replace_once(source,'''    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
''','''    for index in range(count):
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
''','qsearch classical slice')

    for marker in ('CONTEXT_STUDENT_OFFSET','advance_context_accumulator_into','QSEARCH_EVAL_WIDTH'):
        if marker not in source: raise SystemExit(f'missing {marker}')
    path.write_text(source)


def main() -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('path',type=Path); p.add_argument('--hidden',type=int,required=True)
    p.add_argument('--numerator',type=int,required=True); p.add_argument('--denominator',type=int,required=True); a=p.parse_args()
    patch(a.path,hidden=a.hidden,numerator=a.numerator,denominator=a.denominator); return 0

if __name__=='__main__': raise SystemExit(main())
