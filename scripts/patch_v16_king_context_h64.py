#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v16_king_context_h64.py ENGINE_DIR')

root = Path(sys.argv[1])
runtime = root / 'experiments' / 'v14_student_single_runtime.py'
search = root / 'experiments' / 'numba_search.py'

s = runtime.read_text()
const_anchor = 'CP_SCALE = 400\n'
const_replacement = '''CP_SCALE = 400
PIECE_FEATURES = 768
KING_CONTEXT_BUCKETS = 8
BLACK_KING_CONTEXT_OFFSET = PIECE_FEATURES + KING_CONTEXT_BUCKETS
'''
if s.count(const_anchor) != 1:
    raise SystemExit(f'runtime constant anchor count={s.count(const_anchor)}')
s = s.replace(const_anchor, const_replacement, 1)

old = '''@njit(cache=False, inline="always")
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
'''
new = '''@njit(cache=False, inline="always")
def _king_context_bucket(square: int, white: bool) -> int:
    rank = square >> 3
    file = square & 7
    if not white:
        rank = 7 - rank
    return (rank >> 1) * 2 + (1 if file >= 4 else 0)


@njit(cache=False, inline="always")
def infer_absolute768_student_cp(
    accumulator: np.ndarray,
    feature_weights: np.ndarray,
    white_king_square: int,
    black_king_square: int,
    output_weights: np.ndarray,
    output_bias: int,
) -> int:
    """Return the king-context H64 White-perspective correction in centipawns."""
    white_context = PIECE_FEATURES + _king_context_bucket(white_king_square, True)
    black_context = BLACK_KING_CONTEXT_OFFSET + _king_context_bucket(black_king_square, False)
    raw = np.int64(0)
    hidden = accumulator.shape[0]
    for neuron in range(hidden):
        activation = (
            int(accumulator[neuron])
            + int(feature_weights[white_context, neuron])
            + int(feature_weights[black_context, neuron])
        )
        if activation < 0:
            activation = 0
        elif activation > QA:
            activation = QA
        raw += np.int64(activation * activation) * np.int64(output_weights[neuron])
    scaled = trunc_div_scalar(int(raw), QA) + int(output_bias)
    return trunc_div_scalar(scaled * CP_SCALE, QA * QB)
'''
if s.count(old) != 1:
    raise SystemExit(f'runtime inference anchor count={s.count(old)}')
runtime.write_text(s.replace(old, new, 1))

s = search.read_text()
shape_old = 'if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):'
shape_new = 'if STUDENT_FEATURE_WEIGHTS.shape != (784, 64):'
if s.count(shape_old) != 1:
    raise SystemExit(f'search shape anchor count={s.count(shape_old)}')
s = s.replace(shape_old, shape_new, 1)

old = '''    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
'''
new = '''    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
        int(state[EVAL_WHITE_KING]),
        int(state[EVAL_BLACK_KING]),
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
'''
if s.count(old) != 1:
    raise SystemExit(f'search inference anchor count={s.count(old)}')
search.write_text(s.replace(old, new, 1))
