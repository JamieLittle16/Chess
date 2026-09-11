#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''        previous_move = move\n        previous_score = score\n        best_move = move\n        best_score = score\n        root_preferred = move\n        completed_depth = depth\n'''
new = '''        # A lone late-depth root flip is often a horizon/selectivity artifact.  Keep the last\n        # completed choice unless the new move survives one further completed iteration.  The new\n        # move still becomes the next root preference, so genuine improvements confirm naturally.\n        # Restrict this guard to depth 6+ so ordinary shallow iterative-deepening behaviour is\n        # unchanged.\n        late_unconfirmed_flip = depth >= 6 and previous_move >= 0 and move != previous_move\n        if not late_unconfirmed_flip:\n            best_move = move\n            best_score = score\n        previous_move = move\n        previous_score = score\n        root_preferred = move\n        completed_depth = depth\n'''
if s.count(old) != 1:
    raise SystemExit(f'late-root-flip patch mismatch: {s.count(old)}')
p.write_text(s.replace(old, new, 1))
