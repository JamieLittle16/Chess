#!/usr/bin/env python3
"""Add a modest near-equal-position weighting to the Gestalt topology distillation trainer.

The base trainer optimises centipawn residual error uniformly. Search decisions are most sensitive
when the teacher score is near the current alpha/beta region, so this research patch lets those
positions receive extra gradient weight while preserving all data and the exact quantised topology.
A focus weight of zero is exactly the original objective.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_gestalt_search_focused_trainer.py TRAINER.py")
p = Path(sys.argv[1])
s = p.read_text()

old = "p.add_argument('--seed',type=int,default=20260908);return p.parse_args()"
new = "p.add_argument('--seed',type=int,default=20260908);p.add_argument('--focus-weight',type=float,default=0.0);p.add_argument('--focus-cp',type=float,default=450.0);return p.parse_args()"
if s.count(old) != 1:
    raise SystemExit(f"args anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "err=pred-d['target'][ix];gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix);loss+=float(np.abs(err).sum());"
new = "err=pred-d['target'][ix];fw=(1.0+a.focus_weight/(1.0+np.square(np.abs(d['teacher'][ix])/a.focus_cp))).astype(np.float32);gp=np.clip(err,-.5,.5).astype(np.float32)*fw/float(fw.sum());loss+=float((np.abs(err)*fw).sum()/max(1e-9,float(fw.mean())));"
if s.count(old) != 1:
    raise SystemExit(f"gradient anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest()"
new = "'focus_weight':a.focus_weight,'focus_cp':a.focus_cp,'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest()"
if s.count(old) != 1:
    raise SystemExit(f"metadata anchor count={s.count(old)}")
s = s.replace(old, new, 1)

p.write_text(s)
