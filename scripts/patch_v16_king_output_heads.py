#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v16_king_output_heads.py ENGINE_DIR')

root=Path(sys.argv[1])
runtime=root/'experiments'/'v14_student_single_runtime.py'
search=root/'experiments'/'numba_search.py'

s=runtime.read_text()
const_anchor='CP_SCALE = 400\n'
const_replacement='''CP_SCALE = 400
KING_OUTPUT_BUCKETS = 8
'''
if s.count(const_anchor)!=1:
    raise SystemExit(f'runtime constant anchor count={s.count(const_anchor)}')
s=s.replace(const_anchor,const_replacement,1)
old='''@njit(cache=False, inline="always")
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
new='''@njit(cache=False, inline="always")
def _king_output_bucket(square: int, white: bool) -> int:
    rank = square >> 3
    file = square & 7
    if not white:
        rank = 7 - rank
    return (rank >> 1) * 2 + (1 if file >= 4 else 0)


@njit(cache=False, inline="always")
def infer_absolute768_student_cp(
    accumulator: np.ndarray,
    white_king_square: int,
    black_king_square: int,
    output_weights: np.ndarray,
    output_bias: np.ndarray,
) -> int:
    """Return the exact king-conditioned White-perspective student correction in centipawns."""
    pair = _king_output_bucket(white_king_square, True) * KING_OUTPUT_BUCKETS + _king_output_bucket(black_king_square, False)
    raw = np.int64(0)
    hidden = accumulator.shape[0]
    for neuron in range(hidden):
        activation = int(accumulator[neuron])
        if activation < 0:
            activation = 0
        elif activation > QA:
            activation = QA
        raw += np.int64(activation * activation) * np.int64(output_weights[pair, neuron])
    scaled = trunc_div_scalar(int(raw), QA) + int(output_bias[pair])
    return trunc_div_scalar(scaled * CP_SCALE, QA * QB)
'''
if s.count(old)!=1:
    raise SystemExit(f'runtime inference anchor count={s.count(old)}')
runtime.write_text(s.replace(old,new,1))

s=search.read_text()
old_load='''STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_OUTPUT_BIAS = int(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
    raise ValueError("invalid V14 H64 student feature matrix")
if STUDENT_FEATURE_BIAS.shape != (64,) or STUDENT_OUTPUT_WEIGHTS.shape != (64,):
    raise ValueError("invalid V14 H64 student head")
'''
new_load='''STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_OUTPUT_BIAS = np.ascontiguousarray(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1))
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
    raise ValueError("invalid V16 H64 student feature matrix")
if STUDENT_FEATURE_BIAS.shape != (64,) or STUDENT_OUTPUT_WEIGHTS.shape != (64, 64) or STUDENT_OUTPUT_BIAS.shape != (64,):
    raise ValueError("invalid V16 king-conditioned H64 student head")
'''
if s.count(old_load)!=1:
    raise SystemExit(f'search model-load anchor count={s.count(old_load)}')
s=s.replace(old_load,new_load,1)
old_call='''    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
'''
new_call='''    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        int(state[EVAL_WHITE_KING]),
        int(state[EVAL_BLACK_KING]),
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
'''
if s.count(old_call)!=1:
    raise SystemExit(f'search inference anchor count={s.count(old_call)}')
search.write_text(s.replace(old_call,new_call,1))
print('patched king-conditioned output-head runtime')
