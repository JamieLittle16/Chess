#!/usr/bin/env python3
"""Force the exact fused H64 parent->child transport into its caller.

The direct fused updater is already semantically exact and +5% NPS in isolation. Its caller,
_advance_eval_state_into, is inline-always, but the cross-module H64 dispatcher is not. Marking the
fused transport inline-always lets Numba see the fixed 64-lane loop and constant weight arrays in the
search compilation while preserving identical integer operations and API.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]);s=p.read_text()
old='''@njit(cache=False)\ndef advance_absolute768_accumulator_into(\n'''
new='''@njit(cache=False, inline="always")\ndef advance_absolute768_accumulator_into(\n'''
if s.count(old)!=1:
    raise SystemExit(f'updater decorator anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
