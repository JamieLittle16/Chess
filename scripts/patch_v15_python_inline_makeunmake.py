#!/usr/bin/env python3
"""Force the reversible board make/unmake helpers into the compiled search hot path.

Search already inlines eval-state transport before make_move_inplace. Inlining make/unmake exposes
repeated move decoding and board-square accesses to LLVM for CSE/constant propagation while leaving
the exact move semantics and call signatures unchanged.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
for name in ('make_move_inplace','undo_move_inplace'):
    old=f'@njit(cache=False)\ndef {name}('
    new=f'@njit(cache=False, inline="always")\ndef {name}('
    if s.count(old)!=1: raise SystemExit(f'{name} decorator anchor count={s.count(old)}')
    s=s.replace(old,new,1)
p.write_text(s)
