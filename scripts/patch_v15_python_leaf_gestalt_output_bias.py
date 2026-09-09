#!/usr/bin/env python3
"""Consume the scalar output bias emitted by the output-bias H16 trainer.

Apply after patch_v15_python_leaf_gestalt_h16.py. Runtime cost is one integer addition per Gestalt
evaluation and otherwise preserves the leaf-only topology exactly.
"""
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit('usage: patch_v15_python_leaf_gestalt_output_bias.py SEARCH.py')
p=Path(sys.argv[1]);s=p.read_text()
old='''LEAF_GESTALT_OUTPUT_THEM = np.ascontiguousarray(
    _leaf_gestalt_model["output_them"], dtype=np.int16
)
LEAF_GESTALT_SCALE_DEN = int(
'''
new='''LEAF_GESTALT_OUTPUT_THEM = np.ascontiguousarray(
    _leaf_gestalt_model["output_them"], dtype=np.int16
)
LEAF_GESTALT_OUTPUT_BIAS = int(
    np.asarray(_leaf_gestalt_model["output_bias"], dtype=np.int32).reshape(-1)[0]
)
LEAF_GESTALT_SCALE_DEN = int(
'''
if s.count(old)!=1: raise SystemExit(f'model bias anchor count={s.count(old)}')
s=s.replace(old,new,1)
old='''    scaled = trunc_div_scalar(raw, LEAF_GESTALT_QA)
    cp = trunc_div_scalar(
        scaled * LEAF_GESTALT_CP_SCALE,
'''
new='''    scaled = trunc_div_scalar(raw, LEAF_GESTALT_QA) + LEAF_GESTALT_OUTPUT_BIAS
    cp = trunc_div_scalar(
        scaled * LEAF_GESTALT_CP_SCALE,
'''
if s.count(old)!=1: raise SystemExit(f'inference bias anchor count={s.count(old)}')
s=s.replace(old,new,1)
p.write_text(s)
