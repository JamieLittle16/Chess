#!/usr/bin/env python3
"""Apply the Rust-V15 root policy on every iteration while preserving the engine PV.

This wraps the proven root-policy runtime patch, then changes deployment semantics:
- the engine's own preferred/PV move stays first when present;
- policy promotes the best TOP_K alternatives after that PV;
- if no preferred move exists, policy may seed from index zero;
- the policy is consulted on every root iteration, so its ranking can actually affect PVS.

Use only after the one-pass presort patch; otherwise V14's lazy next-best picker can undo the
policy ordering before the root move is searched.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_root_policy_persistent.py SEARCH.py TOP_K")
search = Path(sys.argv[1])
top_k = int(sys.argv[2])
if top_k not in (1, 3):
    raise SystemExit("TOP_K must be 1 or 3")

helper = Path(__file__).with_name("patch_v15_python_root_policy_runtime.py")
subprocess.run([sys.executable, str(helper), str(search), str(top_k)], check=True)
s = search.read_text()


def rep(old: str, new: str, *, label: str) -> None:
    global s
    count = s.count(old)
    if count != 1:
        raise SystemExit(f"{label} count={count} expected=1")
    s = s.replace(old, new, 1)

rep(
'''def _promote_policy_top_k(
    board: np.ndarray,
    side: int,
    castling: int,
    moves: np.ndarray,
    scores: np.ndarray,
    count: int,
) -> None:
    if count <= 1:
        return
''',
'''def _promote_policy_top_k(
    board: np.ndarray,
    side: int,
    castling: int,
    moves: np.ndarray,
    scores: np.ndarray,
    count: int,
    start: int,
) -> None:
    if count - start <= 1:
        return
''',
label="policy helper signature",
)
rep(
'''    limit = min(POLICY_TOP_K, count)
    for index in range(limit):
''',
'''    limit = min(start + POLICY_TOP_K, count)
    for index in range(start, limit):
''',
label="policy helper range",
)
rep(
'''    # Seed only the first completed iteration. Deeper iterations retain the engine's own PV move.
    if depth == 1:
        _promote_policy_top_k(board, side, castling, moves, score_stack[0], count)

    best_move = int(moves[0])
''',
'''    # Preserve the engine's own previous PV when it exists, then let the Rust policy rank the
    # unproven alternatives. With one-pass presort applied there is no later lazy score scan to undo
    # this ordering.
    policy_start = 0
    if preferred != 0 and count > 0 and int(moves[0]) == preferred:
        policy_start = 1
    _promote_policy_top_k(
        board, side, castling, moves, score_stack[0], count, policy_start
    )

    best_move = int(moves[0])
''',
label="persistent root policy call",
)
search.write_text(s)
