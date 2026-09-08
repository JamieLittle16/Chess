#!/usr/bin/env python3
"""Train the king-bucket student as a residual *on top of* packaged V14.

The existing trainer intentionally replaces V14's H64 student by learning teacher - V13.
Game qualification showed that replacement loses playing strength even when Stockfish RMSE improves.
This wrapper reuses the exact same feature/training/quantisation implementation but changes the
learning target to teacher - V14 and evaluates the candidate as V14 + bucket residual.
"""
from pathlib import Path
import os
import sys
import tempfile

src_path = Path(__file__).with_name("train_v15_bucket_student.py")
s = src_path.read_text()

old = "p.add_argument('--hidden',type=int,choices=(16,32),required=True)"
new = "p.add_argument('--hidden',type=int,choices=(8,16,24,32),required=True)"
if s.count(old) != 1:
    raise SystemExit(f"hidden-choice anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "target[i]=sign*max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-a))/CP_SCALE"
new = "target[i]=sign*max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-c))/CP_SCALE"
if s.count(old) != 1:
    raise SystemExit(f"target anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "sign=d['sign'][idx];cand=d['v13'][idx]+sign*np.asarray(corr_cp,dtype=np.float64)/float(den)"
new = "sign=d['sign'][idx];cand=d['v14'][idx]+sign*np.asarray(corr_cp,dtype=np.float64)/float(den)"
if s.count(old) != 1:
    raise SystemExit(f"metric anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = "'architecture':f'kingbucket8-shared-h{a.hidden}x2-antisymmetric-screlu'"
new = "'architecture':f'v14-plus-kingbucket8-residual-h{a.hidden}x2-antisymmetric-screlu'"
if s.count(old) != 1:
    raise SystemExit(f"architecture anchor count={s.count(old)}")
s = s.replace(old, new, 1)

# Keep the original implementation otherwise byte-for-byte equivalent. Execute the generated
# trainer as a standalone script so argparse and __main__ behave exactly as before.
fd, tmp = tempfile.mkstemp(prefix="v15_bucket_residual_", suffix=".py")
os.close(fd)
Path(tmp).write_text(s)
try:
    os.execv(sys.executable, [sys.executable, tmp, *sys.argv[1:]])
finally:
    Path(tmp).unlink(missing_ok=True)
