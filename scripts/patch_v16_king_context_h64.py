#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv)!=2: raise SystemExit('usage: patch_v16_king_context_h64.py ENGINE_DIR')
root=Path(sys.argv[1]); runtime=root/'experiments'/'v14_student_single_runtime.py'; search=root/'experiments'/'numba_search.py'
s=runtime.read_text()
s=s.replace('STUDENT_INPUTS = 768\n', 'STUDENT_INPUTS = 784\nPIECE_FEATURES = 768\nKING_CONTEXT_BUCKETS = 8\nBLACK_KING_CONTEXT_OFFSET = 776\n', 1)
old='''@njit(cache=False, inline="always")\ndef infer_absolute768_student_cp(\n    accumulator: np.ndarray,\n    output_weights: np.ndarray,\n    output_bias: np.ndarray,\n) -> int:\n    raw = int(output_bias[0])\n    for hidden in range(STUDENT_HIDDEN):\n        value = int(accumulator[hidden])\n        if value < 0:\n            value = 0\n        elif value > STUDENT_QA:\n            value = STUDENT_QA\n        raw += ((value * value) // STUDENT_QA) * int(output_weights[hidden])\n    return _trunc_div(raw * STUDENT_CP_SCALE, STUDENT_QA * STUDENT_QB)\n'''
new='''@njit(cache=False, inline="always")\ndef _king_context_bucket(square: int, white: bool) -> int:\n    rank = square >> 3\n    file = square & 7\n    if not white:\n        rank = 7 - rank\n    return (rank >> 1) * 2 + (1 if file >= 4 else 0)\n\n\n@njit(cache=False, inline="always")\ndef infer_absolute768_student_cp(\n    accumulator: np.ndarray,\n    feature_weights: np.ndarray,\n    white_king_square: int,\n    black_king_square: int,\n    output_weights: np.ndarray,\n    output_bias: np.ndarray,\n) -> int:\n    white_context = PIECE_FEATURES + _king_context_bucket(white_king_square, True)\n    black_context = BLACK_KING_CONTEXT_OFFSET + _king_context_bucket(black_king_square, False)\n    raw = int(output_bias[0])\n    for hidden in range(STUDENT_HIDDEN):\n        value = (int(accumulator[hidden]) + int(feature_weights[white_context, hidden]) + int(feature_weights[black_context, hidden]))\n        if value < 0:\n            value = 0\n        elif value > STUDENT_QA:\n            value = STUDENT_QA\n        raw += ((value * value) // STUDENT_QA) * int(output_weights[hidden])\n    return _trunc_div(raw * STUDENT_CP_SCALE, STUDENT_QA * STUDENT_QB)\n'''
if old not in s: raise SystemExit('runtime inference anchor not found')
runtime.write_text(s.replace(old,new,1))

s=search.read_text()
s=s.replace('if STUDENT_FEATURE_WEIGHTS.shape != (768, STUDENT_HIDDEN):', 'if STUDENT_FEATURE_WEIGHTS.shape != (784, STUDENT_HIDDEN):',1)
old='''    student_cp = infer_absolute768_student_cp(\n        eval_state[STUDENT_OFFSET : STUDENT_OFFSET + STUDENT_HIDDEN],\n        STUDENT_OUTPUT_WEIGHTS,\n        STUDENT_OUTPUT_BIAS,\n    )\n'''
new='''    student_cp = infer_absolute768_student_cp(\n        eval_state[STUDENT_OFFSET : STUDENT_OFFSET + STUDENT_HIDDEN],\n        STUDENT_FEATURE_WEIGHTS,\n        int(eval_state[EVAL_WHITE_KING]),\n        int(eval_state[EVAL_BLACK_KING]),\n        STUDENT_OUTPUT_WEIGHTS,\n        STUDENT_OUTPUT_BIAS,\n    )\n'''
if old not in s: raise SystemExit('search inference anchor not found')
search.write_text(s.replace(old,new,1))
