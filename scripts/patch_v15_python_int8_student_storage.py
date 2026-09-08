#!/usr/bin/env python3
"""Store the exact V14 H64 weights in int8 without changing any numeric value.

The shipped int16 tensors have ranges feature=[-32,34], bias=[20,43], output=[-7,6].  All fit in
signed int8 exactly.  Accumulators remain the existing wider integer state, so this is a pure model
storage/cache-footprint experiment rather than requantisation.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_int8_student_storage.py SEARCH.py")
p=Path(sys.argv[1]);s=p.read_text()
old='''STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
'''
new='''# Every shipped quantised value fits signed int8 exactly.  Keep accumulator arithmetic unchanged
# while halving the hot weight-table footprint.
STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int8)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int8)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int8)
'''
if s.count(old)!=1: raise SystemExit(f'int8 model anchor count={s.count(old)}')
s=s.replace(old,new,1)
p.write_text(s)
