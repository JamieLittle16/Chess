#!/usr/bin/env python3
"""Set the ordinary non-check qsearch ceiling in exact packaged Python V14.

The V14 quiescence ceiling is checked only inside `if not checked:`. Checked nodes therefore
continue generating full legal evasions beyond this local tactical ceiling, preserving the already
correct check-evasion semantics while allowing us to tune ordinary qsearch cost toward Rust V15.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_qsearch_cap.py SEARCH.py CAP")
p = Path(sys.argv[1])
cap = int(sys.argv[2])
if cap < 1 or cap > 10:
    raise SystemExit("CAP must be in [1,10]")
s = p.read_text()
old = "MAX_QPLY = 10\n"
if s.count(old) != 1:
    raise SystemExit(f"MAX_QPLY anchor count={s.count(old)}")
s = s.replace(old, f"MAX_QPLY = {cap}\n", 1)
p.write_text(s)
