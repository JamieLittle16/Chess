#!/usr/bin/env python3
"""Defer expensive child state until a V14 move survives shallow pruning.

The exact V14 search advances the full 64-lane student accumulator and computes repetition/history
identity before late-quiet futility can discard a move. This patch prepares the student feature
changes as four scalar encoded deltas, advances only the exact V13 prefix, makes the move and runs
the existing check/futility/LMR gate. Surviving moves then materialise the H64 tail and child key.

No search policy, score, move order or evaluator arithmetic is intended to change; qualification
requires bit-identical fixed-node results on a broad root set.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]);s=p.read_text()

anchor='''@njit(cache=False)
def _negamax(
'''
helpers='''@njit(cache=False, inline="always")
def _student_absolute_feature(signed_piece: int, square: int) -> int:
    color_base = 0 if signed_piece > 0 else 384
    return color_base + (abs(signed_piece) - 1) * 64 + square


@njit(cache=False, inline="always")
def _prepare_student_move_deltas(
    board: np.ndarray, side: int, move: int
) -> tuple[int, int, int, int]:
    """Encode the at-most-four absolute768 feature changes for one legal move.

    Positive values mean add feature(value-1); negative values mean remove feature(-value-1);
    zero is unused. This preparation is O(1) and does no hidden-lane arithmetic.
    """
    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    moving_signed = int(board[from_square])
    placed_signed = side * promotion if promotion else moving_signed

    d0 = -(_student_absolute_feature(moving_signed, from_square) + 1)
    d1 = _student_absolute_feature(placed_signed, to_square) + 1
    d2 = 0
    d3 = 0

    captured_square = to_square
    captured_signed = int(board[to_square])
    if move & FLAG_EP:
        captured_square = to_square - 8 * side
        captured_signed = int(board[captured_square])
    if captured_signed != EMPTY:
        # Preserve the old arithmetic order: moving removal, captured removal, placed addition.
        d1 = -(_student_absolute_feature(captured_signed, captured_square) + 1)
        d2 = _student_absolute_feature(placed_signed, to_square) + 1

    if move & FLAG_CASTLE:
        # Castling cannot capture, so all four slots are available.
        if to_square == 6:
            rook_from, rook_to = 7, 5
        elif to_square == 2:
            rook_from, rook_to = 0, 3
        elif to_square == 62:
            rook_from, rook_to = 63, 61
        else:
            rook_from, rook_to = 56, 59
        rook_signed = side * ROOK
        d2 = -(_student_absolute_feature(rook_signed, rook_from) + 1)
        d3 = _student_absolute_feature(rook_signed, rook_to) + 1
    return d0, d1, d2, d3


@njit(cache=False, inline="always")
def _apply_student_encoded_delta(accumulator: np.ndarray, encoded: int) -> None:
    if encoded == 0:
        return
    sign = 1
    feature = encoded - 1
    if encoded < 0:
        sign = -1
        feature = -encoded - 1
    for neuron in range(STUDENT_HIDDEN):
        accumulator[neuron] += sign * int(STUDENT_FEATURE_WEIGHTS[feature, neuron])


@njit(cache=False, inline="always")
def _advance_prepared_student_into(
    parent: np.ndarray,
    child: np.ndarray,
    d0: int,
    d1: int,
    d2: int,
    d3: int,
) -> None:
    for neuron in range(STUDENT_HIDDEN):
        child[neuron] = parent[neuron]
    _apply_student_encoded_delta(child, d0)
    _apply_student_encoded_delta(child, d1)
    _apply_student_encoded_delta(child, d2)
    _apply_student_encoded_delta(child, d3)


@njit(cache=False)
def _negamax(
'''
if s.count(anchor)!=1:raise SystemExit(f'negamax anchor count={s.count(anchor)}')
s=s.replace(anchor,helpers,1)

old='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )

        # Adaptive verified LMR v3. Captures/promotions, both killers, checks, nodes in check and
'''
new='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        sd0, sd1, sd2, sd3 = _prepare_student_move_deltas(board, side, move)
        # Materialise only the cheap exact-V13 prefix before the pruning gate. The H64 tail is
        # prepared above but not touched unless the move survives.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )

        # Adaptive verified LMR v3. Captures/promotions, both killers, checks, nodes in check and
'''
if s.count(old)!=1:raise SystemExit(f'child-state pre-prune anchor count={s.count(old)}')
s=s.replace(old,new,1)

old2='''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        if gives_check:
            reduction = 0
'''
new2='''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        # The move survived all pre-search pruning. Materialise the exact H64 child accumulator and
        # repetition/history identity now. The prepared feature deltas reproduce the old accumulator
        # update without reading the already-mutated board.
        _advance_prepared_student_into(
            eval_stack[ply, STUDENT_OFFSET:EVAL_WIDTH],
            eval_stack[ply + 1, STUDENT_OFFSET:EVAL_WIDTH],
            sd0,
            sd1,
            sd2,
            sd3,
        )
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )

        if gives_check:
            reduction = 0
'''
if s.count(old2)!=1:raise SystemExit(f'post-prune anchor count={s.count(old2)}')
s=s.replace(old2,new2,1)
p.write_text(s)
