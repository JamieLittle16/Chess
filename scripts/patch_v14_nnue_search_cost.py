#!/usr/bin/env python3
"""Add a score-disabled 128-wide Chess768 accumulator to exact V13 search state.

This is a performance probe, not an evaluator candidate.  The synthetic network score is never
read.  Therefore fixed-node search signatures must remain bit-for-bit V13 while we measure the cost
of carrying and sparsely updating a production-shaped two-perspective accumulator through the real
search tree.
"""
from __future__ import annotations

import argparse
from pathlib import Path

WIDTH_MARKER = "EVAL_WIDTH = 8\n"
WIDTH_REPLACEMENT = '''NNUE_COST_HIDDEN = 128
NNUE_COST_WHITE_OFFSET = 8
NNUE_COST_BLACK_OFFSET = NNUE_COST_WHITE_OFFSET + NNUE_COST_HIDDEN
EVAL_WIDTH = NNUE_COST_BLACK_OFFSET + NNUE_COST_HIDDEN

# Deterministic synthetic Chess768 rows used only to measure accumulator-carry cost.
# The probe score is never read by search and therefore cannot alter V13 decisions.
_NNUE_COST_SEQ = np.arange(768 * NNUE_COST_HIDDEN, dtype=np.int32)
NNUE_COST_WEIGHTS = (((_NNUE_COST_SEQ * 17 + 23) % 97) - 48).astype(np.int16).reshape(
    768, NNUE_COST_HIDDEN
)
NNUE_COST_BIAS = (((np.arange(NNUE_COST_HIDDEN, dtype=np.int32) * 13 + 7) % 97) - 48).astype(
    np.int16
)


@njit(cache=False, inline="always")
def _nnue_cost_feature(perspective: int, signed_piece: int, square: int) -> int:
    own_piece = (signed_piece > 0) == (perspective == WHITE)
    base = 0 if own_piece else 384
    local_square = square if perspective == WHITE else square ^ 56
    return base + (abs(signed_piece) - 1) * 64 + local_square


@njit(cache=False, inline="never")
def _build_nnue_cost_state_into(board: np.ndarray, state: np.ndarray) -> None:
    for neuron in range(NNUE_COST_HIDDEN):
        bias = int(NNUE_COST_BIAS[neuron])
        state[NNUE_COST_WHITE_OFFSET + neuron] = bias
        state[NNUE_COST_BLACK_OFFSET + neuron] = bias
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        wf = _nnue_cost_feature(WHITE, signed_piece, square)
        bf = _nnue_cost_feature(-WHITE, signed_piece, square)
        for neuron in range(NNUE_COST_HIDDEN):
            state[NNUE_COST_WHITE_OFFSET + neuron] += int(NNUE_COST_WEIGHTS[wf, neuron])
            state[NNUE_COST_BLACK_OFFSET + neuron] += int(NNUE_COST_WEIGHTS[bf, neuron])


@njit(cache=False, inline="always")
def _nnue_cost_delta_piece(
    child: np.ndarray, signed_piece: int, square: int, sign: int
) -> None:
    wf = _nnue_cost_feature(WHITE, signed_piece, square)
    bf = _nnue_cost_feature(-WHITE, signed_piece, square)
    for neuron in range(NNUE_COST_HIDDEN):
        child[NNUE_COST_WHITE_OFFSET + neuron] += sign * int(NNUE_COST_WEIGHTS[wf, neuron])
        child[NNUE_COST_BLACK_OFFSET + neuron] += sign * int(NNUE_COST_WEIGHTS[bf, neuron])


@njit(cache=False, inline="never")
def _advance_nnue_cost_state_into(
    board: np.ndarray,
    side: int,
    move: int,
    parent: np.ndarray,
    child: np.ndarray,
) -> None:
    for neuron in range(NNUE_COST_HIDDEN):
        child[NNUE_COST_WHITE_OFFSET + neuron] = parent[NNUE_COST_WHITE_OFFSET + neuron]
        child[NNUE_COST_BLACK_OFFSET + neuron] = parent[NNUE_COST_BLACK_OFFSET + neuron]

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

    _nnue_cost_delta_piece(child, moving_signed, from_square, -1)
    if captured_signed != EMPTY:
        _nnue_cost_delta_piece(child, captured_signed, captured_square, -1)
    _nnue_cost_delta_piece(child, placed_signed, to_square, 1)

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
        _nnue_cost_delta_piece(child, rook_signed, rook_from, -1)
        _nnue_cost_delta_piece(child, rook_signed, rook_to, 1)
'''


def patch(path: Path) -> None:
    source = path.read_text()
    if "NNUE_COST_HIDDEN" in source:
        raise SystemExit("source already contains the NNUE search-cost probe")
    if source.count(WIDTH_MARKER) != 1:
        raise SystemExit(f"EVAL_WIDTH marker count={source.count(WIDTH_MARKER)}")
    source = source.replace(WIDTH_MARKER, WIDTH_REPLACEMENT, 1)

    build_marker = "    state[EVAL_RESIDUAL_BLACK] = black_residual\n"
    if source.count(build_marker) != 1:
        raise SystemExit(f"build marker count={source.count(build_marker)}")
    source = source.replace(
        build_marker,
        build_marker + "    _build_nnue_cost_state_into(board, state)\n",
        1,
    )

    advance_marker = "    _advance_residual_state_into(board, side, move, parent, child)\n"
    if source.count(advance_marker) != 1:
        raise SystemExit(f"advance marker count={source.count(advance_marker)}")
    source = source.replace(
        advance_marker,
        advance_marker + "    _advance_nnue_cost_state_into(board, side, move, parent, child)\n",
        1,
    )

    # The score-disabled cost probe must not touch either evaluation function.
    if source.count("def _evaluate_state_classical(") != 1 or source.count("def _evaluate_state(") != 1:
        raise SystemExit("unexpected evaluation structure")
    if "correction = correction // 6" not in source:
        raise SystemExit("qualified V13 1/6 residual baseline missing")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
