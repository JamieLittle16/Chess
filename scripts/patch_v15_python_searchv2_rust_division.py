#!/usr/bin/env python3
"""Make Python Search-v2 history gravity truncate signed division toward zero like Rust."""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = "    gravity = current * abs(bonus) // HISTORY_LIMIT\n"
new = "    gravity_magnitude = abs(current) * abs(bonus) // HISTORY_LIMIT\n    gravity = gravity_magnitude if current >= 0 else -gravity_magnitude\n"
if s.count(old) != 1:
    raise SystemExit(f"expected one history gravity expression, found {s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
