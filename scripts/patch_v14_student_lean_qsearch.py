#!/usr/bin/env python3
"""Make the H64 V14 student active only at the qsearch entry horizon.

Normal alpha-beta nodes keep the exact full 1/12 student. At qply == 0, stand-pat also uses the
student. Deeper qsearch plies use exact V13 evaluation and update only the first eight V13 state
cells, avoiding neural accumulator transport/inference throughout tactical capture chains.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()
    if "_evaluate_state_v13_only" in source:
        raise SystemExit("lean qsearch patch already applied")
    if "STUDENT_OFFSET" not in source or "STUDENT_SCALE_DEN" not in source:
        raise SystemExit("expected an already-integrated single-student source")

    eval_anchor = '''    return score + correction + student_cp


@njit(cache=False, inline="never")
def _advance_residual_state_into(
'''
    eval_replacement = '''    return score + correction + student_cp


@njit(cache=False, inline="always")
def _evaluate_state_v13_only(side: int, state: np.ndarray) -> int:
    """Exact V13 /6 evaluation, ignoring the appended V14 student cells."""
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
def _advance_residual_state_into(
'''
    source = replace_once(source, eval_anchor, eval_replacement, "V13-only evaluator insertion")

    stand_pat_old = '''        stand_pat = _evaluate_state(side, eval_stack[ply])
'''
    stand_pat_new = '''        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
'''
    source = replace_once(source, stand_pat_old, stand_pat_new, "qsearch stand-pat")

    qadvance_old = '''    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
'''
    qadvance_new = '''    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
        # qualified incremental updater performs no work in its appended student-accumulator tail.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
'''
    source = replace_once(source, qadvance_old, qadvance_new, "qsearch incremental state")

    if source.count("_evaluate_state_v13_only(") != 2:
        raise SystemExit("unexpected V13-only evaluator structure")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
