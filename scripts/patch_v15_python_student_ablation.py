#!/usr/bin/env python3
"""Ablate the packaged V14 H64 student from live search and its accumulator hot path.

The exact V13 residual/classical evaluator remains. EVAL_WIDTH is collapsed to the V13 prefix, so
existing build/advance calls receive zero-length student slices and perform no H64 lane work. The
combined evaluator is replaced by the exact V13-only evaluator to avoid retaining the student bias.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
EVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN
'''
new='''STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
# V15 ablation lane: retain model constants for import/package parity, but allocate only the exact
# V13 prefix in live search state. Existing student build/advance slices are therefore empty.
EVAL_WIDTH = EVAL_V13_WIDTH
'''
if s.count(old)!=1:raise SystemExit('EVAL_WIDTH anchor drift')
s=s.replace(old,new,1)
start=s.index('@njit(cache=False, inline="always")\ndef _evaluate_state(side: int, state: np.ndarray) -> int:')
end=s.index('\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_v13_only',start)
oldblock=s[start:end]
newblock='''@njit(cache=False, inline="always")
def _evaluate_state(side: int, state: np.ndarray) -> int:
    # Student-ablation lane: exact V13 /6 evaluation is the complete live leaf evaluator.
    score = _evaluate_state_classical(side, state)
    if side == WHITE:
        correction = int(state[EVAL_RESIDUAL_WHITE]) - int(state[EVAL_RESIDUAL_BLACK])
    else:
        correction = int(state[EVAL_RESIDUAL_BLACK]) - int(state[EVAL_RESIDUAL_WHITE])
    correction += RESIDUAL_BIAS
    if RESIDUAL_CLAMP > 0:
        if correction > RESIDUAL_CLAMP:
            correction = RESIDUAL_CLAMP
        elif correction < -RESIDUAL_CLAMP:
            correction = -RESIDUAL_CLAMP
    correction = correction // 6
    return score + correction
'''
s=s[:start]+newblock+s[end:]
p.write_text(s)
