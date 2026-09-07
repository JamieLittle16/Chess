"""V14 compact Chess768 NNUE runtime substrate.

This module is deliberately *not* wired into the production search yet. It exists so the exact
Bullet feature map, quantised file layout, full-refresh accumulator, incremental move delta, and
integer inference arithmetic can be qualified independently before a learned checkpoint is allowed
to change engine behaviour.

The feature contract is pinned to Bullet commit 629ee50000b2afb7b3337595401c830d3b1e0f42:
dual-perspective Chess768, SCReLU, QA=255, QB=64, scale=400.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from numba import njit

from .numba_core import (
    EMPTY,
    FLAG_CASTLE,
    FLAG_EP,
    ROOK,
    WHITE,
    move_from,
    move_promotion,
    move_to,
)

NNUE_INPUTS = 768
NNUE_QA = 255
NNUE_QB = 64
NNUE_SCALE = 400


@njit(cache=False, inline="always")
def chess768_feature_index(perspective: int, signed_piece: int, square: int) -> int:
    """Return the exact global-perspective equivalent of Bullet's stm-relative Chess768 index."""
    own_piece = (signed_piece > 0) == (perspective == WHITE)
    ownership_base = 0 if own_piece else 384
    local_square = square if perspective == WHITE else square ^ 56
    return ownership_base + (abs(signed_piece) - 1) * 64 + local_square


@njit(cache=False)
def build_chess768_accumulator_into(
    board: np.ndarray,
    perspective: int,
    feature_weights: np.ndarray,
    feature_bias: np.ndarray,
    out: np.ndarray,
) -> None:
    """Build one perspective accumulator from scratch into an int32 destination."""
    hidden = feature_bias.shape[0]
    for neuron in range(hidden):
        out[neuron] = int(feature_bias[neuron])
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        feature = chess768_feature_index(perspective, signed_piece, square)
        for neuron in range(hidden):
            out[neuron] += int(feature_weights[feature, neuron])


@njit(cache=False, inline="always")
def _apply_feature_delta(
    white_acc: np.ndarray,
    black_acc: np.ndarray,
    feature_weights: np.ndarray,
    signed_piece: int,
    square: int,
    sign: int,
) -> None:
    white_feature = chess768_feature_index(WHITE, signed_piece, square)
    black_feature = chess768_feature_index(-WHITE, signed_piece, square)
    hidden = white_acc.shape[0]
    for neuron in range(hidden):
        white_acc[neuron] += sign * int(feature_weights[white_feature, neuron])
        black_acc[neuron] += sign * int(feature_weights[black_feature, neuron])


@njit(cache=False)
def advance_chess768_accumulators_into(
    board: np.ndarray,
    side: int,
    move: int,
    parent_white: np.ndarray,
    parent_black: np.ndarray,
    child_white: np.ndarray,
    child_black: np.ndarray,
    feature_weights: np.ndarray,
) -> None:
    """Advance both global perspective accumulators from the pre-move board."""
    hidden = parent_white.shape[0]
    for neuron in range(hidden):
        child_white[neuron] = parent_white[neuron]
        child_black[neuron] = parent_black[neuron]

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

    _apply_feature_delta(
        child_white, child_black, feature_weights, moving_signed, from_square, -1
    )
    if captured_signed != EMPTY:
        _apply_feature_delta(
            child_white, child_black, feature_weights, captured_signed, captured_square, -1
        )
    _apply_feature_delta(
        child_white, child_black, feature_weights, placed_signed, to_square, 1
    )

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
        _apply_feature_delta(
            child_white, child_black, feature_weights, rook_signed, rook_from, -1
        )
        _apply_feature_delta(
            child_white, child_black, feature_weights, rook_signed, rook_to, 1
        )


@njit(cache=False, inline="always")
def _screlu_quantised(value: int) -> int:
    if value <= 0:
        return 0
    if value >= NNUE_QA:
        return NNUE_QA * NNUE_QA
    return value * value


@njit(cache=False, inline="always")
def _div_trunc_zero(value: int, divisor: int) -> int:
    if value >= 0:
        return value // divisor
    return -((-value) // divisor)


@njit(cache=False)
def evaluate_chess768_accumulators(
    side: int,
    white_acc: np.ndarray,
    black_acc: np.ndarray,
    output_weights: np.ndarray,
    output_bias: int,
) -> int:
    """Evaluate the quantised `(768 -> H)x2 -> 1` SCReLU network exactly like Bullet's example."""
    us = white_acc if side == WHITE else black_acc
    them = black_acc if side == WHITE else white_acc
    hidden = us.shape[0]

    output = 0
    for neuron in range(hidden):
        output += _screlu_quantised(int(us[neuron])) * int(output_weights[neuron])
    for neuron in range(hidden):
        output += _screlu_quantised(int(them[neuron])) * int(output_weights[hidden + neuron])

    output = _div_trunc_zero(output, NNUE_QA)
    output += int(output_bias)
    output *= NNUE_SCALE
    return _div_trunc_zero(output, NNUE_QA * NNUE_QB)


def load_bullet_quantised(path: str | Path, hidden_size: int) -> tuple[np.ndarray, ...]:
    """Load Bullet `quantised.bin` for the frozen V14 simple architecture."""
    if hidden_size not in (64, 96, 128, 192):
        raise ValueError(f"unsupported frozen V14-A hidden size: {hidden_size}")

    path = Path(path)
    payload = path.read_bytes()
    values_required = NNUE_INPUTS * hidden_size + hidden_size + 2 * hidden_size + 1
    bytes_required = values_required * 2
    if len(payload) < bytes_required or len(payload) - bytes_required >= 64:
        raise ValueError(
            f"unexpected quantised network size {len(payload)} for H={hidden_size}; "
            f"expected {bytes_required} bytes plus <64 bytes padding"
        )

    values = np.frombuffer(payload[:bytes_required], dtype="<i2")
    offset = 0
    l0w_count = NNUE_INPUTS * hidden_size
    feature_weights = values[offset : offset + l0w_count].reshape(NNUE_INPUTS, hidden_size).copy()
    offset += l0w_count
    feature_bias = values[offset : offset + hidden_size].copy()
    offset += hidden_size
    output_weights = values[offset : offset + 2 * hidden_size].copy()
    offset += 2 * hidden_size
    output_bias = np.int16(values[offset])
    return feature_weights, feature_bias, output_weights, output_bias
