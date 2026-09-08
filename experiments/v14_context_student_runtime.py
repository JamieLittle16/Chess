"""King-context single-accumulator student runtime for Little Gambit V14.

Each ordinary absolute768 piece-square feature is conditioned on a coarse pair of king zones:
(white king queenside/centre/kingside) x (black king queenside/centre/kingside).  The resulting
9*768 sparse feature space gives a compact H64 student direct king-safety context while retaining
one accumulator and O(changed pieces * hidden) ordinary move updates.

When a king crosses a zone boundary the feature namespace changes for every piece.  That event is
rare, so the child accumulator is rebuilt exactly from the pre-move board plus move semantics.
"""
from __future__ import annotations

import numpy as np
from numba import njit

from .numba_core import EMPTY, FLAG_CASTLE, FLAG_EP, KING, ROOK, move_from, move_promotion, move_to

QA = 255
QB = 64
CP_SCALE = 400
CONTEXTS = 9
BASE_FEATURES = 768
FEATURES = CONTEXTS * BASE_FEATURES


@njit(cache=False, inline="always")
def king_file_zone(square: int) -> int:
    file = square & 7
    if file <= 2:
        return 0
    if file <= 4:
        return 1
    return 2


@njit(cache=False, inline="always")
def king_context(white_king: int, black_king: int) -> int:
    return king_file_zone(white_king) * 3 + king_file_zone(black_king)


@njit(cache=False, inline="always")
def absolute768_feature_index(signed_piece: int, square: int) -> int:
    color_base = 0 if signed_piece > 0 else 384
    return color_base + (abs(signed_piece) - 1) * 64 + square


@njit(cache=False, inline="always")
def contextual_feature_index(context: int, signed_piece: int, square: int) -> int:
    return context * BASE_FEATURES + absolute768_feature_index(signed_piece, square)


@njit(cache=False)
def build_context_accumulator_into(
    board: np.ndarray,
    context: int,
    feature_weights: np.ndarray,
    feature_bias: np.ndarray,
    out: np.ndarray,
) -> None:
    hidden = out.shape[0]
    for neuron in range(hidden):
        out[neuron] = int(feature_bias[neuron])
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        feature = contextual_feature_index(context, signed_piece, square)
        for neuron in range(hidden):
            out[neuron] += int(feature_weights[feature, neuron])


@njit(cache=False, inline="always")
def _apply_context_delta(
    accumulator: np.ndarray,
    feature_weights: np.ndarray,
    context: int,
    signed_piece: int,
    square: int,
    sign: int,
) -> None:
    feature = contextual_feature_index(context, signed_piece, square)
    hidden = accumulator.shape[0]
    for neuron in range(hidden):
        accumulator[neuron] += sign * int(feature_weights[feature, neuron])


@njit(cache=False, inline="always")
def child_king_context(
    white_king: int,
    black_king: int,
    side: int,
    move: int,
    moving_signed: int,
) -> int:
    if abs(moving_signed) == KING:
        if side > 0:
            white_king = move_to(move)
        else:
            black_king = move_to(move)
    return king_context(white_king, black_king)


@njit(cache=False)
def _rebuild_child_context_accumulator_into(
    board: np.ndarray,
    side: int,
    move: int,
    child_context: int,
    feature_weights: np.ndarray,
    feature_bias: np.ndarray,
    out: np.ndarray,
) -> None:
    """Build exact post-move accumulator while the board still contains the parent position."""
    hidden = out.shape[0]
    for neuron in range(hidden):
        out[neuron] = int(feature_bias[neuron])

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    moving_signed = int(board[from_square])
    placed_signed = side * promotion if promotion else moving_signed
    captured_square = to_square
    if move & FLAG_EP:
        captured_square = to_square - 8 * side

    rook_from = -1
    rook_to = -1
    if move & FLAG_CASTLE:
        if to_square == 6:
            rook_from, rook_to = 7, 5
        elif to_square == 2:
            rook_from, rook_to = 0, 3
        elif to_square == 62:
            rook_from, rook_to = 63, 61
        else:
            rook_from, rook_to = 56, 59

    for square in range(64):
        signed_piece = int(board[square])
        if square == from_square or square == captured_square or square == rook_from:
            signed_piece = EMPTY
        if square == to_square:
            signed_piece = placed_signed
        elif square == rook_to:
            signed_piece = side * ROOK
        if signed_piece == EMPTY:
            continue
        feature = contextual_feature_index(child_context, signed_piece, square)
        for neuron in range(hidden):
            out[neuron] += int(feature_weights[feature, neuron])


@njit(cache=False)
def advance_context_accumulator_into(
    board: np.ndarray,
    side: int,
    move: int,
    white_king: int,
    black_king: int,
    parent_context: int,
    parent: np.ndarray,
    child: np.ndarray,
    feature_weights: np.ndarray,
    feature_bias: np.ndarray,
) -> int:
    moving_signed = int(board[move_from(move)])
    next_context = child_king_context(white_king, black_king, side, move, moving_signed)
    if next_context != parent_context:
        _rebuild_child_context_accumulator_into(
            board, side, move, next_context, feature_weights, feature_bias, child
        )
        return next_context

    hidden = parent.shape[0]
    for neuron in range(hidden):
        child[neuron] = parent[neuron]

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    captured_square = to_square
    captured_signed = int(board[to_square])
    if move & FLAG_EP:
        captured_square = to_square - 8 * side
        captured_signed = int(board[captured_square])
    placed_signed = side * promotion if promotion else moving_signed

    _apply_context_delta(child, feature_weights, parent_context, moving_signed, from_square, -1)
    if captured_signed != EMPTY:
        _apply_context_delta(child, feature_weights, parent_context, captured_signed, captured_square, -1)
    _apply_context_delta(child, feature_weights, parent_context, placed_signed, to_square, 1)

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
        _apply_context_delta(child, feature_weights, parent_context, rook_signed, rook_from, -1)
        _apply_context_delta(child, feature_weights, parent_context, rook_signed, rook_to, 1)
    return next_context


@njit(cache=False, inline="always")
def trunc_div_scalar(value: int, divisor: int) -> int:
    if value >= 0:
        return value // divisor
    return -((-value) // divisor)


@njit(cache=False, inline="always")
def infer_context_student_cp(
    accumulator: np.ndarray,
    output_weights: np.ndarray,
    output_bias: int,
) -> int:
    raw = np.int64(0)
    for neuron in range(accumulator.shape[0]):
        activation = int(accumulator[neuron])
        if activation < 0:
            activation = 0
        elif activation > QA:
            activation = QA
        raw += np.int64(activation * activation) * np.int64(output_weights[neuron])
    scaled = trunc_div_scalar(int(raw), QA) + int(output_bias)
    return trunc_div_scalar(scaled * CP_SCALE, QA * QB)
