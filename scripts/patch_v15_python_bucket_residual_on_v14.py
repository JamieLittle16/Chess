#!/usr/bin/env python3
"""Layer a trained king-bucket residual on top of exact packaged V14 H64.

We first reuse the parity-tested bucket runtime patch, then append the original V14 absolute-H64
accumulator/head back into the evaluation state. The bucket model therefore acts only as the
additional teacher-V14 correction it was trained to predict.
"""
from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_bucket_residual_on_v14.py SEARCH.py HIDDEN")
search = Path(sys.argv[1])
hidden = int(sys.argv[2])
subprocess.run(
    [sys.executable, str(Path(__file__).with_name("patch_v15_python_bucket_student_runtime.py")), str(search), str(hidden)],
    check=True,
)
s = search.read_text()

anchor = '''STUDENT_QA = 255
STUDENT_QB = 64
STUDENT_CP_SCALE = 400
'''
insert = '''STUDENT_QA = 255
STUDENT_QB = 64
STUDENT_CP_SCALE = 400

_legacy_model = np.load(Path(__file__).with_name("v14_student_h64.npz"), allow_pickle=False)
LEGACY_FEATURE_WEIGHTS = np.ascontiguousarray(_legacy_model["feature_weights"], dtype=np.int16)
LEGACY_FEATURE_BIAS = np.ascontiguousarray(_legacy_model["feature_bias"], dtype=np.int16)
LEGACY_OUTPUT_WEIGHTS = np.ascontiguousarray(_legacy_model["output_weights"], dtype=np.int16)
LEGACY_OUTPUT_BIAS = int(np.asarray(_legacy_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _legacy_model
if LEGACY_FEATURE_WEIGHTS.shape != (768, 64):
    raise ValueError("invalid V14 H64 feature matrix")
if LEGACY_FEATURE_BIAS.shape != (64,) or LEGACY_OUTPUT_WEIGHTS.shape != (64,):
    raise ValueError("invalid V14 H64 head")
LEGACY_SCALE_NUM = 1
LEGACY_SCALE_DEN = 12
'''
if s.count(anchor) != 1:
    raise SystemExit(f"legacy model anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

anchor = '''STUDENT_WHITE_OFFSET = EVAL_V13_WIDTH
STUDENT_BLACK_OFFSET = STUDENT_WHITE_OFFSET + STUDENT_HIDDEN
EVAL_WIDTH = STUDENT_BLACK_OFFSET + STUDENT_HIDDEN
'''
insert = '''STUDENT_WHITE_OFFSET = EVAL_V13_WIDTH
STUDENT_BLACK_OFFSET = STUDENT_WHITE_OFFSET + STUDENT_HIDDEN
BUCKET_END = STUDENT_BLACK_OFFSET + STUDENT_HIDDEN
LEGACY_OFFSET = BUCKET_END
LEGACY_END = LEGACY_OFFSET + 64
EVAL_WIDTH = LEGACY_END
'''
if s.count(anchor) != 1:
    raise SystemExit(f"layout anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

# The already-tested bucket helpers used EVAL_WIDTH as the end of their black accumulator. Once
# legacy H64 is appended, freeze those slices at BUCKET_END instead.
count = s.count("STUDENT_BLACK_OFFSET:EVAL_WIDTH")
if count < 2:
    raise SystemExit(f"bucket black-slice anchor count={count}")
s = s.replace("STUDENT_BLACK_OFFSET:EVAL_WIDTH", "STUDENT_BLACK_OFFSET:BUCKET_END")

anchor = '''    _build_bucket_student_into(board, state)
'''
insert = '''    _build_bucket_student_into(board, state)
    build_absolute768_accumulator_into(
        board,
        LEGACY_FEATURE_WEIGHTS,
        LEGACY_FEATURE_BIAS,
        state[LEGACY_OFFSET:LEGACY_END],
    )
'''
if s.count(anchor) != 1:
    raise SystemExit(f"build anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

anchor = '''    student_cp = _infer_bucket_student_white_cp(state)
    if side != WHITE:
        student_cp = -student_cp
    return score + correction + student_cp
'''
insert = '''    student_cp = _infer_bucket_student_white_cp(state)
    if side != WHITE:
        student_cp = -student_cp
    legacy_cp = infer_absolute768_student_cp(
        state[LEGACY_OFFSET:LEGACY_END],
        LEGACY_OUTPUT_WEIGHTS,
        LEGACY_OUTPUT_BIAS,
    )
    if side != WHITE:
        legacy_cp = -legacy_cp
    legacy_cp = trunc_div_scalar(legacy_cp * LEGACY_SCALE_NUM, LEGACY_SCALE_DEN)
    return score + correction + legacy_cp + student_cp
'''
if s.count(anchor) != 1:
    raise SystemExit(f"eval anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

anchor = '''    _advance_bucket_student_into(board, side, move, parent, child)
'''
insert = '''    _advance_bucket_student_into(board, side, move, parent, child)
    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[LEGACY_OFFSET:LEGACY_END],
        child[LEGACY_OFFSET:LEGACY_END],
        LEGACY_FEATURE_WEIGHTS,
    )
'''
if s.count(anchor) != 1:
    raise SystemExit(f"advance anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)
search.write_text(s)
