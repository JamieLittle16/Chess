#!/usr/bin/env python3
"""Defer the V14 H64 accumulator update until a late quiet survives futility pruning.

Apply after patch_v16_python_rust_history.py.  Classical/V13 child state is still advanced before
make_move, so legality/check/repetition/search semantics are unchanged.  The absolute768 H64 tail is
piece-square only; after make_move its exact delta can be reconstructed from move metadata and the
returned captured piece without needing the parent board.  Every searched child therefore receives
bit-identical H64 state, while a futility-pruned late quiet never pays for the 64-lane update.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_defer_student.py SEARCH.py")
path = Path(sys.argv[1])
s = path.read_text()

start_anchor = '@njit(cache=False, inline="always")\ndef _advance_eval_state_into('
end_anchor = '\n@njit(cache=False, inline="always")\ndef _repetition_piece_index'
start = s.index(start_anchor)
end = s.index(end_anchor, start)
block = s[start:end]
student_call = '''    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )
'''
if block.count(student_call) != 1:
    raise SystemExit(f"student advance anchor count={block.count(student_call)}")
base_block = block.replace(
    'def _advance_eval_state_into(', 'def _advance_eval_state_without_student_into(', 1
).replace(student_call, '', 1)

prepared_helper = '''

@njit(cache=False, inline="always")
def _advance_student_after_make_into(
    board_after: np.ndarray,
    side: int,
    move: int,
    captured_piece: int,
    captured_square: int,
    parent: np.ndarray,
    child: np.ndarray,
) -> None:
    # Reproduce advance_absolute768_accumulator_into exactly, but derive the move payload from the
    # child board plus make_move's captured-piece result.  The student has no king-bucket state.
    for neuron in range(STUDENT_HIDDEN):
        child[STUDENT_OFFSET + neuron] = parent[STUDENT_OFFSET + neuron]

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    placed_signed = int(board_after[to_square])
    moving_signed = side * PAWN if promotion else placed_signed

    feature = (0 if moving_signed > 0 else 384) + (abs(moving_signed) - 1) * 64 + from_square
    for neuron in range(STUDENT_HIDDEN):
        child[STUDENT_OFFSET + neuron] -= int(STUDENT_FEATURE_WEIGHTS[feature, neuron])

    if captured_piece != EMPTY:
        feature = (0 if captured_piece > 0 else 384) + (abs(captured_piece) - 1) * 64 + captured_square
        for neuron in range(STUDENT_HIDDEN):
            child[STUDENT_OFFSET + neuron] -= int(STUDENT_FEATURE_WEIGHTS[feature, neuron])

    feature = (0 if placed_signed > 0 else 384) + (abs(placed_signed) - 1) * 64 + to_square
    for neuron in range(STUDENT_HIDDEN):
        child[STUDENT_OFFSET + neuron] += int(STUDENT_FEATURE_WEIGHTS[feature, neuron])

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
        feature = (0 if rook_signed > 0 else 384) + (abs(rook_signed) - 1) * 64 + rook_from
        for neuron in range(STUDENT_HIDDEN):
            child[STUDENT_OFFSET + neuron] -= int(STUDENT_FEATURE_WEIGHTS[feature, neuron])
        feature = (0 if rook_signed > 0 else 384) + (abs(rook_signed) - 1) * 64 + rook_to
        for neuron in range(STUDENT_HIDDEN):
            child[STUDENT_OFFSET + neuron] += int(STUDENT_FEATURE_WEIGHTS[feature, neuron])
'''

s = s[:start] + base_block + '\n\n' + block + prepared_helper + s[end:]

old = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
'''
new = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_without_student_into(
            board, side, move, eval_stack[ply], eval_stack[ply + 1]
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
'''
if s.count(old) != 1:
    raise SystemExit(f"negamax deferred-state anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        if gives_check:
'''
new = '''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        _advance_student_after_make_into(
            board,
            side,
            move,
            captured_piece,
            captured_square,
            eval_stack[ply],
            eval_stack[ply + 1],
        )

        if gives_check:
'''
if s.count(old) != 1:
    raise SystemExit(f"post-futility student anchor count={s.count(old)}")
s = s.replace(old, new, 1)

path.write_text(s)
print('deferred H64 accumulator past late-quiet futility; searched-child state remains exact')
