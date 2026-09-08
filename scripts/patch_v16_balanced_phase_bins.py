#!/usr/bin/env python3
"""Patch the H16 phase-head trainer to use corpus-balanced four-way phase cutpoints."""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_balanced_phase_bins.py TRAINER.py")
p=Path(sys.argv[1]);s=p.read_text()
old="  teacher[i]=t;v13[i]=a;v14[i]=c;target[i]=max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-a))/CP_SCALE;stmw[i]=bool(b.turn);codes[i]=smap[r['split']];ph[i]=min(heads-1,(phase*heads)//(MAX_PHASE+1)) if heads>1 else 0\n"
new="  teacher[i]=t;v13[i]=a;v14[i]=c;target[i]=max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-a))/CP_SCALE;stmw[i]=bool(b.turn);codes[i]=smap[r['split']]\n  if heads==4: ph[i]=0 if phase<=21 else (1 if phase==22 else (2 if phase==23 else 3))\n  else: ph[i]=min(heads-1,(phase*heads)//(MAX_PHASE+1)) if heads>1 else 0\n"
if s.count(old)!=1:raise SystemExit(f'phase assignment anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
