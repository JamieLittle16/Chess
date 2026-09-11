#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''        previous_move = move\n        previous_score = score\n        best_move = move\n        best_score = score\n        root_preferred = move\n        completed_depth = depth\n'''
new = '''        # A lone late-depth root flip with nearly unchanged value is often a horizon/selectivity\n        # artifact.  Keep the last completed choice unless the new move survives one further\n        # completed iteration.  The new move still becomes the next root preference, so genuine\n        # improvements confirm naturally.  Large tactical score swings and mates are trusted\n        # immediately.\n        late_unconfirmed_flip = (\n            depth >= 6\n            and previous_move >= 0\n            and move != previous_move\n            and abs(score) < MATE_THRESHOLD\n            and abs(score - previous_score) <= 80\n        )\n        if not late_unconfirmed_flip:\n            best_move = move\n            best_score = score\n        previous_move = move\n        previous_score = score\n        root_preferred = move\n        completed_depth = depth\n'''
if s.count(old) != 1:
    raise SystemExit(f'late-root-flip patch mismatch: {s.count(old)}')
p.write_text(s.replace(old, new, 1))
