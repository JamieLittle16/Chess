#!/usr/bin/env python3
"""Defer the H64 accumulator update until a quiet survives late-quiet futility.

The V13 prefix is sufficient for exact king/check status and the accepted pruning tests. For moves
that survive pruning, reconstruct the exact absolute768 delta from the already-made board plus the
signed captured-piece metadata returned by make_move_inplace. This keeps child evaluator state
bit-identical while avoiding 64-lane work for moves that never enter recursive search.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

anchor = '''@njit(cache=False, inline="always")
def _repetition_piece_index(signed_piece: int) -> int:
'''
helper = '''@njit(cache=False, inline="always")
def _student_apply_delta(
    accumulator: np.ndarray, signed_piece: int, square: int, sign: int
) -> None:
    color_base = 0 if signed_piece > 0 else 384
    feature = color_base + (abs(signed_piece) - 1) * 64 + square
    for neuron in range(STUDENT_HIDDEN):
        accumulator[neuron] += sign * int(STUDENT_FEATURE_WEIGHTS[feature, neuron])


@njit(cache=False)
def _advance_student_after_move_into(
    board: np.ndarray,
    side: int,
    move: int,
    captured_signed: int,
    captured_square: int,
    parent: np.ndarray,
    child: np.ndarray,
) -> None:
    for neuron in range(STUDENT_HIDDEN):
        child[neuron] = parent[neuron]

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    placed_signed = int(board[to_square])
    moving_signed = side * PAWN if promotion else placed_signed

    _student_apply_delta(child, moving_signed, from_square, -1)
    if captured_signed != EMPTY:
        _student_apply_delta(child, captured_signed, captured_square, -1)
    _student_apply_delta(child, placed_signed, to_square, 1)

    if move & FLAG_CASTLE:
        if to_square == 6:
            rook_from, rook_to = 7, 5
        elif to_square == 2:
            rook_from, rook_to = 0, 3
        elif to_square == 62:
            rook_from, rook_to = 63, 61
        else:
            rook_from, rook_to = 56, 59
        rook_signed = side * ROOK
        _student_apply_delta(child, rook_signed, rook_from, -1)
        _student_apply_delta(child, rook_signed, rook_to, 1)


@njit(cache=False, inline="always")
def _repetition_piece_index(signed_piece: int) -> int:
'''
if s.count(anchor) != 1:
    raise SystemExit(f"helper anchor count={s.count(anchor)}")
s = s.replace(anchor, helper, 1)

start = s.index("def _negamax(")
end = s.index("\n\n\n@njit(cache=False)\ndef _root(", start)
head, block, tail = s[:start], s[start:end], s[end:]
old = "        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n"
new = '''        # The H64 tail is dead work if late-quiet futility rejects this move. Advance only the
        # exact V13 prefix until the pruning decision is known.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
'''
if block.count(old) != 1:
    raise SystemExit(f"negamax advance count={block.count(old)}")
block = block.replace(old, new, 1)
needle = '''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        if gives_check:
'''
replacement = '''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        # This move really enters search: materialise the exact H64 child accumulator now. The
        # already-made board contains the placed piece; make_move_inplace supplied exact signed
        # capture metadata, including en-passant.
        _advance_student_after_move_into(
            board,
            side,
            move,
            captured_piece,
            captured_square,
            eval_stack[ply, STUDENT_OFFSET:EVAL_WIDTH],
            eval_stack[ply + 1, STUDENT_OFFSET:EVAL_WIDTH],
        )

        if gives_check:
'''
if block.count(needle) != 1:
    raise SystemExit(f"defer insertion count={block.count(needle)}")
block = block.replace(needle, replacement, 1)
p.write_text(head + block + tail)
