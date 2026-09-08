#!/usr/bin/env python3
"""Return immediately when the H64 updater receives the intentional empty qsearch slice."""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''    hidden = parent.shape[0]\n    from_square = move_from(move)\n'''
new='''    hidden = parent.shape[0]\n    if hidden == 0:\n        return\n    from_square = move_from(move)\n'''
if s.count(old)!=1: raise SystemExit(f'fused updater anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
