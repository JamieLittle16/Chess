"""Single-accumulator absolute piece-square NNUE substrate for Python V14 cost experiments.

Unlike dual-perspective Chess768, this representation maintains one accumulator for an absolute
signed-piece feature map. A trained value head would predict from White's perspective; search would
negate for Black-to-move. This module is initially shadow-only so no score is consumed by V13.

The hot-path parent-to-child transport deliberately uses explicit scalar loops. The dual-perspective
slice-copy experiment showed that Numba slice assignment is substantially slower in this context.
"""
from __future__ import annotations

import numpy as np
from numba import njit

from .numba_core import EMPTY, FLAG_CASTLE, FLAG_EP, ROOK, move_from, move_promotion, move_to

NNUE_INPUTS = 768


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


@njit(cache=False, inline="always")
def _apply_absolute_delta(
    accumulator: np.ndarray,
    feature_weights: np.ndarray,
    signed_piece: int,
    square: int,
    sign: int,
) -> None:
    feature = absolute768_feature_index(signed_piece, square)
    hidden = accumulator.shape[0]
    for neuron in range(hidden):
        accumulator[neuron] += sign * int(feature_weights[feature, neuron])


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
    for neuron in range(hidden):
        child[neuron] = parent[neuron]

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
    _apply_absolute_delta(child, feature_weights, moving_signed, from_square, -1)
    if captured_signed != EMPTY:
        _apply_absolute_delta(child, feature_weights, captured_signed, captured_square, -1)
    _apply_absolute_delta(child, feature_weights, placed_signed, to_square, 1)

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
        _apply_absolute_delta(child, feature_weights, rook_signed, rook_from, -1)
        _apply_absolute_delta(child, feature_weights, rook_signed, rook_to, 1)
