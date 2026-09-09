#!/usr/bin/env python3
"""Replace the expensive pre-deadline one-ply fallback in the production timed search.

The old fallback fully advanced/evaluated every root child and generated every opponent reply before
starting the CPU deadline. In normal competition play depth 1 completes, so that work is discarded
while still being charged by the referee wall clock.

This patch changes only iterative_search_stateful_timed_cached. It keeps a legal deterministic
fallback (first generated legal move) for pathological zero-depth returns. Normal search semantics
are unchanged once depth 1 completes. Qualification must therefore explicitly certify that the
competition-clock workload never returns depth 0 before this can be accepted.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_fast_fallback.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

fn = s.index('@njit(cache=False)\ndef iterative_search_stateful_timed_cached(')
end = len(s)
for marker in ('\n\n@njit(cache=False)\ndef iterative_search_stateful_timed(', '\n\ndef evaluate('):
    pos = s.find(marker, fn + 1)
    if pos >= 0:
        end = min(end, pos)
block = s[fn:end]

comment = '    # Rule-aware emergency fallback:'
c0 = block.find(comment)
if c0 < 0:
    raise SystemExit('timed cached fallback comment not found')
hard = block.find('    hard_ms = max(1, hard_ms)\n', c0)
if hard < 0:
    raise SystemExit('timed cached hard_ms anchor not found')

replacement = '''    # Fast emergency fallback.  The full one-ply static scan used to run before the CPU deadline,
    # so the referee charged it even though its answer was discarded whenever depth 1 completed.
    # Keep the first legal move solely as a pathological zero-depth safety value; normal timed
    # qualification must certify completed_depth >= 1 on every tested competition position.
    best_move = int(move_stack[0, 0])
    best_score = 0

'''
block = block[:c0] + replacement + block[hard:]
s = s[:fn] + block + s[end:]
p.write_text(s)
