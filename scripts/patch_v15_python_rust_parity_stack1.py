#!/usr/bin/env python3
"""Assemble the first coherent Rust-parity search stack on exact packaged Python V14.

This intentionally combines architectural pieces that were previously tested in isolation:
- Rust-style board-key TT identity (rule draws remain checked before TT probes),
- side-specific main + one-ply continuation history,
- history-conditioned verified LMR and once-scored scout-node updates,
- one-pass stable move ordering so history is not paid through V14's repeated O(n^2) next-best scans,
- Rust-exact signed history gravity (integer division truncates toward zero).

The resulting search remains pure Python/Numba source for the competition package.
"""
from __future__ import annotations

from pathlib import Path
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_rust_parity_stack1.py SEARCH.py")

search = Path(sys.argv[1]).resolve()
repo = Path(__file__).resolve().parents[1]

# Apply the two semantic components first. They are deliberately kept as independently auditable
# patchers because both have already been qualified separately.
subprocess.run(
    [sys.executable, str(repo / "scripts/patch_v15_python_rust_tt_parity.py"), str(search)],
    check=True,
)
subprocess.run(
    [sys.executable, str(repo / "scripts/patch_v15_python_searchv2_history.py"), str(search)],
    check=True,
)

s = search.read_text()


def rep(old: str, new: str, n: int = 1, label: str = "") -> None:
    global s
    count = s.count(old)
    if count != n:
        raise SystemExit(f"{label or old[:50]} count={count} expected={n}")
    s = s.replace(old, new, n)


# Python // floors negative values, whereas Rust signed integer division truncates toward zero.
# History gravity must match Rust exactly or negative history drifts by one point per update.
old = '''@njit(cache=False, inline="always")
def _history_update_entry(current: int, requested_bonus: int) -> int:
    bonus = max(-HISTORY_MAX_UPDATE, min(HISTORY_MAX_UPDATE, requested_bonus))
    gravity = current * abs(bonus) // HISTORY_LIMIT
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
'''
new = '''@njit(cache=False, inline="always")
def _history_update_entry(current: int, requested_bonus: int) -> int:
    bonus = max(-HISTORY_MAX_UPDATE, min(HISTORY_MAX_UPDATE, requested_bonus))
    product = current * abs(bonus)
    gravity = product // HISTORY_LIMIT if product >= 0 else -((-product) // HISTORY_LIMIT)
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))
'''
rep(old, new, label="Rust signed history gravity")

# Score ordinary move lists once and materialise the stable descending order once. This preserves
# V14's tie behaviour (generator order wins ties) while avoiding repeated next-best scans.
old = '''def _order_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
) -> None:
    """Score legal moves; stable ordering is materialised lazily as search consumes it."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
'''
new = '''def _order_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
) -> None:
    """Score once, then materialise V14's stable descending order once."""
    for index in range(count):
        scores[index] = _move_order_score(board, int(moves[index]), preferred)
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
'''
rep(old, new, label="ordinary one-pass ordering")

old = '''def _order_moves_with_killers(
    board: np.ndarray,
    side: int,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    previous_context: int,
    main_history: np.ndarray,
    continuation_history: np.ndarray,
) -> None:
    """Order PV/tacticals, killers, then ordinary quiets by main+continuation history."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            elif not _is_tactical(board, move):
                context = _move_history_context(board, move)
                score += _history_score(
                    side, previous_context, context, main_history, continuation_history
                )
        scores[index] = score
'''
new = '''def _order_moves_with_killers(
    board: np.ndarray,
    side: int,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    previous_context: int,
    main_history: np.ndarray,
    continuation_history: np.ndarray,
) -> None:
    """Score PV/tacticals/killers/history once, then consume the stable order linearly."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            elif not _is_tactical(board, move):
                context = _move_history_context(board, move)
                score += _history_score(
                    side, previous_context, context, main_history, continuation_history
                )
        scores[index] = score
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
'''
rep(old, new, label="history one-pass ordering")

old = '''def _order_root_moves_with_history(
    board: np.ndarray,
    side: int,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    main_history: np.ndarray,
) -> None:
    """Root ordering uses side-specific main history; there is no predecessor context."""
    side_index = 0 if side == WHITE else 1
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000 and not _is_tactical(board, move):
            context = _move_history_context(board, move)
            score += int(main_history[side_index, context])
        scores[index] = score
'''
new = '''def _order_root_moves_with_history(
    board: np.ndarray,
    side: int,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    main_history: np.ndarray,
) -> None:
    """Root main-history ordering, scored and stably sorted once."""
    side_index = 0 if side == WHITE else 1
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000 and not _is_tactical(board, move):
            context = _move_history_context(board, move)
            score += int(main_history[side_index, context])
        scores[index] = score
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score
'''
rep(old, new, label="root one-pass history ordering")

# qsearch and normal search share the ply-indexed list; root has a separate list. All three are now
# already sorted before iteration, so the lazy next-best materialisation must disappear.
old = '        _pick_next_scored_move(moves, score_stack[ply], index, count)\n'
rep(old, '', n=2, label="ply lazy pick removal")
old = '        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
rep(old, '', n=1, label="root lazy pick removal")

# The TT patch intentionally leaves the old history-context array allocated as zeroes to avoid a
# broad signature rewrite. It is no longer part of TT identity or child hashing, so it is cold state.
if 'TT_CONTEXTS_OFFSET' in s:
    raise SystemExit('history-sensitive TT storage survived stack assembly')
if s.count('_pick_next_scored_move(moves,') != 0:
    raise SystemExit('live lazy move picker remains')

search.write_text(s)
