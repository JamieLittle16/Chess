#!/usr/bin/env python3
"""Fuse the exact V14 absolute768 accumulator update into one 64-lane pass.

V14 copies the parent accumulator, then traverses all 64 lanes once for each piece-square delta.
That is 3-6 full passes and repeatedly reads/writes the child array.  This patch preserves the same
integer arithmetic but computes each child lane once:

    child[lane] = parent[lane] - from [- capture] + to [- rook_from + rook_to]

The common quiet-move and capture paths are split outside the lane loop so there are no per-lane
feature-presence branches.  API and evaluator/search semantics are unchanged.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
start=s.index('@njit(cache=False)\ndef advance_absolute768_accumulator_into(')
end=s.index('\n\n@njit(cache=False, inline="always")\ndef trunc_div_scalar',start)
old=s[start:end]
new='''@njit(cache=False)\ndef advance_absolute768_accumulator_into(\n    board: np.ndarray,\n    side: int,\n    move: int,\n    parent: np.ndarray,\n    child: np.ndarray,\n    feature_weights: np.ndarray,\n) -> None:\n    hidden = parent.shape[0]\n    from_square = move_from(move)\n    to_square = move_to(move)\n    promotion = move_promotion(move)\n    moving_signed = int(board[from_square])\n    placed_signed = side * promotion if promotion else moving_signed\n\n    from_feature = absolute768_feature_index(moving_signed, from_square)\n    to_feature = absolute768_feature_index(placed_signed, to_square)\n\n    captured_square = to_square\n    captured_signed = int(board[to_square])\n    if move & FLAG_EP:\n        captured_square = to_square - 8 * side\n        captured_signed = int(board[captured_square])\n\n    # Split the overwhelmingly common paths before the lane loop.  This keeps one load/store of the\n    # accumulator lane and two/three weight-row reads rather than copy + repeated read/modify/write.\n    if captured_signed == EMPTY and not (move & FLAG_CASTLE):\n        for neuron in range(hidden):\n            value = int(parent[neuron])\n            value -= int(feature_weights[from_feature, neuron])\n            value += int(feature_weights[to_feature, neuron])\n            child[neuron] = value\n        return\n\n    if captured_signed != EMPTY:\n        captured_feature = absolute768_feature_index(captured_signed, captured_square)\n        for neuron in range(hidden):\n            value = int(parent[neuron])\n            value -= int(feature_weights[from_feature, neuron])\n            value -= int(feature_weights[captured_feature, neuron])\n            value += int(feature_weights[to_feature, neuron])\n            child[neuron] = value\n        return\n\n    # Castling cannot capture or promote. Preserve V14's exact update order within each lane.\n    if to_square == 6:\n        rook_from, rook_to = 7, 5\n    elif to_square == 2:\n        rook_from, rook_to = 0, 3\n    elif to_square == 62:\n        rook_from, rook_to = 63, 61\n    else:\n        rook_from, rook_to = 56, 59\n    rook_signed = side * ROOK\n    rook_from_feature = absolute768_feature_index(rook_signed, rook_from)\n    rook_to_feature = absolute768_feature_index(rook_signed, rook_to)\n    for neuron in range(hidden):\n        value = int(parent[neuron])\n        value -= int(feature_weights[from_feature, neuron])\n        value += int(feature_weights[to_feature, neuron])\n        value -= int(feature_weights[rook_from_feature, neuron])\n        value += int(feature_weights[rook_to_feature, neuron])\n        child[neuron] = value\n'''
if 'advance_absolute768_accumulator_into' not in old: raise SystemExit('function anchor mismatch')
p.write_text(s[:start]+new+s[end:])
