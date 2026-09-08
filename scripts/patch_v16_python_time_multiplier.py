#!/usr/bin/env python3
"""Scale only the compiled-search allocation, preserving all existing emergency/headroom logic."""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v16_python_time_multiplier.py AGENT.py MULTIPLIER")
p = Path(sys.argv[1])
multiplier = float(sys.argv[2])
if not 1.0 <= multiplier <= 1.5:
    raise SystemExit("multiplier must lie in [1.0, 1.5]")
s = p.read_text()
old = "    allocation = _move_budget_ms(board, time_left_ms, legal_moves)\n"
new = (
    "    allocation = _move_budget_ms(board, time_left_ms, legal_moves)\n"
    f"    allocation *= {multiplier!r}\n"
    "    # The existing hard-budget fractions below remain the safety boundary. The multiplier\n"
    "    # only converts a little more clock bank into search; it does not remove emergency policy.\n"
)
if s.count(old) != 1:
    raise SystemExit(f"allocation anchor count={s.count(old)}")
p.write_text(s.replace(old, new, 1))
print(f"patched time multiplier={multiplier}")
