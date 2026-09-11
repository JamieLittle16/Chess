#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''        if depth >= 6 and now_ticks >= soft_deadline and stable_transitions >= 2:\n            break\n'''
new = '''        # Decision-rich roots are exactly where shallow stability can be deceptive.\n        # Keep searching to the existing hard allocation when branching is high and the\n        # position has not yet entered a long quiet phase; ordinary/forced roots retain\n        # the proven soft-stop behaviour.\n        if (\n            depth >= 6\n            and now_ticks >= soft_deadline\n            and stable_transitions >= 2\n            and not (count >= 18 and halfmove_clock < 12)\n        ):\n            break\n'''
if s.count(old) != 1:
    raise SystemExit(f'rich-root patch mismatch: {s.count(old)}')
p.write_text(s.replace(old, new, 1))
