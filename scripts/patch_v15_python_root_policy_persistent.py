#!/usr/bin/env python3
"""Make the distilled root policy persist as challenger ordering across iterative depths.

The engine's own preferred/PV move remains untouched at index zero after depth one. The policy only
promotes candidate challengers behind it, so it cannot override deeper search evidence.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_root_policy_persistent.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

old = '''@njit(cache=False)\ndef _promote_policy_top_k(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    moves: np.ndarray,\n    scores: np.ndarray,\n    count: int,\n) -> None:\n'''
new = '''@njit(cache=False)\ndef _promote_policy_top_k(\n    board: np.ndarray,\n    side: int,\n    castling: int,\n    moves: np.ndarray,\n    scores: np.ndarray,\n    count: int,\n    start_index: int,\n) -> None:\n'''
if s.count(old) != 1:
    raise SystemExit(f"policy helper signature anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    limit = min(POLICY_TOP_K, count)\n    for index in range(limit):\n'''
new = '''    start_index = max(0, min(start_index, count))\n    limit = min(start_index + POLICY_TOP_K, count)\n    for index in range(start_index, limit):\n'''
if s.count(old) != 1:
    raise SystemExit(f"policy selection anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    # Seed only the first completed iteration. Deeper iterations retain the engine's own PV move.\n    if depth == 1:\n        _promote_policy_top_k(board, side, castling, moves, score_stack[0], count)\n\n    best_move = int(moves[0])\n'''
new = '''    # At depth one the policy may seed the whole root order. On later iterations the engine's\n    # own preferred/PV move stays first and the policy only orders the challengers behind it.\n    _promote_policy_top_k(\n        board, side, castling, moves, score_stack[0], count, 0 if depth == 1 else 1\n    )\n\n    best_move = int(moves[0])\n'''
if s.count(old) != 1:
    raise SystemExit(f"policy root-call anchor count={s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
print('persistent root policy enabled')
