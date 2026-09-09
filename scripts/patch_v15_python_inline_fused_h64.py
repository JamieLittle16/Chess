#!/usr/bin/env python3
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''@njit(cache=False)\ndef advance_absolute768_accumulator_into(\n'''
new='''@njit(cache=False, inline="always")\ndef advance_absolute768_accumulator_into(\n'''
if s.count(old)!=1: raise SystemExit(f'updater decorator anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
