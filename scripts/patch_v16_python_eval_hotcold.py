#!/usr/bin/env python3
"""Split the large incremental-eval transition into a tiny hot quiet path and a cold special path.

The original transition is retained byte-for-byte (apart from its name/decorator) as the
non-inline special helper.  The inline wrapper handles only ordinary non-capturing,
non-promotion, non-EP, non-castling moves, which dominate the recursive search.  This reduces
recursive LLVM IR expansion without paying a function-call boundary on the common path.
"""
from __future__ import annotations

from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_eval_hotcold.py NUMBA_SEARCH_PY")

path = Path(sys.argv[1])
text = path.read_text()
anchor = '''@njit(cache=False, inline="always")\ndef _advance_eval_state_into(\n'''
if text.count(anchor) != 1:
    raise SystemExit(f"expected one eval-transition anchor, found {text.count(anchor)}")

cold = '''@njit(cache=False, inline="never")\ndef _advance_eval_state_special_into(\n'''
text = text.replace(anchor, cold, 1)

insert_anchor = cold
wrapper = '''@njit(cache=False, inline="always")
def _advance_eval_state_into(
    board: np.ndarray,
    side: int,
    move: int,
    parent: np.ndarray,
    child: np.ndarray,
) -> None:
    """Fast ordinary-move eval transition; rare structural moves use the cold full helper."""
    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    captured_signed = int(board[to_square])

    if promotion != 0 or captured_signed != EMPTY or (move & (FLAG_EP | FLAG_CASTLE)) != 0:
        _advance_eval_state_special_into(board, side, move, parent, child)
        return

    child[EVAL_PHASE] = parent[EVAL_PHASE]
    child[EVAL_BASE] = parent[EVAL_BASE]
    child[EVAL_WHITE_BISHOPS] = parent[EVAL_WHITE_BISHOPS]
    child[EVAL_BLACK_BISHOPS] = parent[EVAL_BLACK_BISHOPS]
    child[EVAL_WHITE_KING] = parent[EVAL_WHITE_KING]
    child[EVAL_BLACK_KING] = parent[EVAL_BLACK_KING]

    moving_signed = int(board[from_square])
    moving_piece = abs(moving_signed)
    if moving_piece == KING:
        if side == WHITE:
            child[EVAL_WHITE_KING] = to_square
        else:
            child[EVAL_BLACK_KING] = to_square
    else:
        child[EVAL_BASE] -= _base_contribution(moving_signed, from_square)
        child[EVAL_BASE] += _base_contribution(moving_signed, to_square)

    _advance_residual_state_into(board, side, move, parent, child)
    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )


'''
text = text.replace(insert_anchor, wrapper + insert_anchor, 1)
path.write_text(text)
print("patched eval transition: inline ordinary path + non-inline exact special path")
