"""Incremental absolute768 student runtime for Python V14 search experiments.

The trained student predicts a White-perspective correction on top of exact V13. This module keeps
one quantised piece-square accumulator and provides exact scalar SCReLU inference.

V14 fused transport computes the complete parent->child accumulator in one neuron pass. Ordinary
moves therefore read/write each accumulator cell once rather than copying the whole vector and then
walking it again for every feature delta. Empty accumulator slices (used by lean qsearch below qply
0) return immediately, avoiding all neural move-decoding work on tactical continuation plies.
"""
from __future__ import annotations

import numpy as np
from numba import njit

from .numba_core import EMPTY, FLAG_CASTLE, FLAG_EP, ROOK, move_from, move_promotion, move_to

QA = 255
QB = 64
CP_SCALE = 400


@njit(cache=False, inline="always")
def absolute768_feature_index(signed_piece: int, square: int) -> int:
    color_base = 0 if signed_piece > 0 else 384
    return color_base + (abs(signed_piece) - 1) * 64 + square


@njit(cache=False)
def build_absolute768_accumulator_into(
    board: np.ndarray,
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
        feature = absolute768_feature_index(signed_piece, square)
        for neuron in range(hidden):
            out[neuron] += int(feature_weights[feature, neuron])


@njit(cache=False)
def advance_absolute768_accumulator_into(
    board: np.ndarray,
    side: int,
    move: int,
    parent: np.ndarray,
    child: np.ndarray,
    feature_weights: np.ndarray,
) -> None:
    hidden = parent.shape[0]
    if hidden == 0:
        return

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    moving_signed = int(board[from_square])

    captured_square = to_square
    captured_signed = int(board[to_square])
    if move & FLAG_EP:
        captured_square = to_square - 8 * side
        captured_signed = int(board[captured_square])

    placed_signed = side * promotion if promotion else moving_signed
    from_feature = absolute768_feature_index(moving_signed, from_square)
    to_feature = absolute768_feature_index(placed_signed, to_square)
    captured_feature = -1
    if captured_signed != EMPTY:
        captured_feature = absolute768_feature_index(captured_signed, captured_square)

    rook_from_feature = -1
    rook_to_feature = -1
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
        rook_from_feature = absolute768_feature_index(rook_signed, rook_from)
        rook_to_feature = absolute768_feature_index(rook_signed, rook_to)

    # One complete pass preserves the exact integer result while avoiding 4-6 separate walks over
    # the H64 vector. The accumulator's conservative legal-position bound is far below int32 range.
    for neuron in range(hidden):
        value = int(parent[neuron])
        value -= int(feature_weights[from_feature, neuron])
        if captured_feature >= 0:
            value -= int(feature_weights[captured_feature, neuron])
        value += int(feature_weights[to_feature, neuron])
        if rook_from_feature >= 0:
            value -= int(feature_weights[rook_from_feature, neuron])
            value += int(feature_weights[rook_to_feature, neuron])
        child[neuron] = value


@njit(cache=False, inline="always")
def trunc_div_scalar(value: int, divisor: int) -> int:
    if value >= 0:
        return value // divisor
    return -((-value) // divisor)


@njit(cache=False, inline="always")
def infer_absolute768_student_cp(
    accumulator: np.ndarray,
    output_weights: np.ndarray,
    output_bias: int,
) -> int:
    """Return the exact quantised White-perspective student correction in centipawns."""
    raw = np.int64(0)
    hidden = accumulator.shape[0]
    for neuron in range(hidden):
        activation = int(accumulator[neuron])
        if activation < 0:
            activation = 0
        elif activation > QA:
            activation = QA
        raw += np.int64(activation * activation) * np.int64(output_weights[neuron])
    scaled = trunc_div_scalar(int(raw), QA) + int(output_bias)
    return trunc_div_scalar(scaled * CP_SCALE, QA * QB)
