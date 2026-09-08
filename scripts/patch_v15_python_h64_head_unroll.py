#!/usr/bin/env python3
"""Unroll the exact 64-lane H64 SCReLU/output reduction without changing arithmetic.

Usage: patch_v15_python_h64_head_unroll.py RUNTIME.py FACTOR
FACTOR is 4 or 8. The total raw int64 sum is identical; independent partial sums merely expose more
instruction-level parallelism to LLVM and avoid a loop-carried dependency on every neuron.
"""
from pathlib import Path
import sys

if len(sys.argv)!=3: raise SystemExit('usage: patch_v15_python_h64_head_unroll.py RUNTIME.py {4|8}')
p=Path(sys.argv[1]);factor=int(sys.argv[2])
if factor not in (4,8): raise SystemExit('factor must be 4 or 8')
s=p.read_text()
anchor='''@njit(cache=False, inline="always")\ndef infer_absolute768_student_cp(\n'''
start=s.find(anchor)
if start<0: raise SystemExit('infer anchor not found')
prefix=s[:start]
lines=['@njit(cache=False, inline="always")','def infer_absolute768_student_cp(','    accumulator: np.ndarray,','    output_weights: np.ndarray,','    output_bias: int,',') -> int:','    """Return the exact quantised White-perspective student correction in centipawns."""']
for i in range(factor): lines.append(f'    raw{i} = np.int64(0)')
lines += ['    hidden = accumulator.shape[0]',f'    limit = hidden - hidden % {factor}',f'    for neuron in range(0, limit, {factor}):']
for i in range(factor):
    lines += [f'        activation{i} = int(accumulator[neuron + {i}])',f'        if activation{i} < 0:',f'            activation{i} = 0',f'        elif activation{i} > QA:',f'            activation{i} = QA',f'        raw{i} += np.int64(activation{i} * activation{i}) * np.int64(output_weights[neuron + {i}])']
lines.append('    raw = np.int64(0)')
for i in range(factor): lines.append(f'    raw += raw{i}')
lines += ['    for neuron in range(limit, hidden):','        activation = int(accumulator[neuron])','        if activation < 0:','            activation = 0','        elif activation > QA:','            activation = QA','        raw += np.int64(activation * activation) * np.int64(output_weights[neuron])','    scaled = trunc_div_scalar(int(raw), QA) + int(output_bias)','    return trunc_div_scalar(scaled * CP_SCALE, QA * QB)','']
p.write_text(prefix+'\n'.join(lines))
