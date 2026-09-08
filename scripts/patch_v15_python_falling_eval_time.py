#!/usr/bin/env python3
"""Require a stable root score not to be meaningfully falling before banking time."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_falling_eval_time.py SEARCH.py FALLING_MARGIN_CP")
p = Path(sys.argv[1])
margin = int(sys.argv[2])
if margin not in (0, 10, 20):
    raise SystemExit("margin must be 0, 10, or 20")
s = p.read_text()
old = "if previous_move == move and abs(score - previous_score) <= 35:"
new = f"if previous_move == move and abs(score - previous_score) <= 35 and score >= previous_score - {margin}:"
count = s.count(old)
if count != 2:
    raise SystemExit(f"stability anchor count={count}, expected 2")
s = s.replace(old, new)
p.write_text(s)
print({'falling_margin_cp': margin, 'patched_occurrences': count})
