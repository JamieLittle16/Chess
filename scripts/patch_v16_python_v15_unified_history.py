#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()


def one(old: str, new: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor count {n} for:\n{old[:180]}")
    s = s.replace(old, new, 1)


# Replace the V15 LMR-only history constants with one coherent main+continuation history geometry.
one(
    """# Lean Search-v2 LMR confidence.  Never participates in move ordering.
LEAN_LMR_HISTORY_LIMIT = 16_384
LEAN_LMR_HISTORY_MAX_UPDATE = 2_048
LEAN_LMR_HISTORY_THRESHOLD = 2048
""",
    """# V16 coherent quiet-history model: side-specific main history plus one-ply continuation.
# This replaces V15's LMR-only 2x384 table so ordering and reductions learn from one signal.
QUIET_HISTORY_CONTEXTS = 6 * 64
QUIET_HISTORY_MAIN_ENTRIES = 2 * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_ENTRIES = QUIET_HISTORY_CONTEXTS * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES
QUIET_HISTORY_STORAGE_SIZE = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES
QUIET_HISTORY_LIMIT = 16_384
QUIET_HISTORY_MAX_UPDATE = 2_048
QUIET_HISTORY_LMR_THRESHOLD = 4_096
""",
)

# Replace move ordering so ordinary quiets receive learned main+continuation scores while
# preferred/tactical/killer bands preserve their existing priority and packed metadata.
start = s.index('@njit(cache=False)\ndef _order_moves_with_killers(')
end = s.index('\n\n\n@njit(cache=False)\ndef _is_tactical', start)
new_order = '''@njit(cache=False, inline="always")
def _quiet_history_context(board: np.ndarray, move: int) -> int:
    piece = abs(int(board[move_from(move)]))
    return (piece - 1) * 64 + move_to(move)


@njit(cache=False, inline="always")
def _quiet_history_score(side: int, previous: int, current: int, table: np.ndarray) -> int:
    side_index = 0 if side == WHITE else 1
    score = int(table[side_index * QUIET_HISTORY_CONTEXTS + current])
    if previous >= 0:
        score += int(table[QUIET_HISTORY_CONT_OFFSET + previous * QUIET_HISTORY_CONTEXTS + current])
    return score


@njit(cache=False, inline="always")
def _quiet_history_depth_bonus(depth: int) -> int:
    return min(QUIET_HISTORY_MAX_UPDATE, 32 * depth * depth + 64 * depth)


@njit(cache=False, inline="always")
def _quiet_history_update(
    side: int, previous: int, current: int, requested_bonus: int, table: np.ndarray
) -> None:
    bonus = max(-QUIET_HISTORY_MAX_UPDATE, min(QUIET_HISTORY_MAX_UPDATE, requested_bonus))
    side_index = 0 if side == WHITE else 1
    main_index = side_index * QUIET_HISTORY_CONTEXTS + current
    current_value = int(table[main_index])
    gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
    table[main_index] = np.int16(
        max(-QUIET_HISTORY_LIMIT, min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity))
    )
    if previous >= 0:
        cont_index = QUIET_HISTORY_CONT_OFFSET + previous * QUIET_HISTORY_CONTEXTS + current
        current_value = int(table[cont_index])
        gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
        table[cont_index] = np.int16(
            max(-QUIET_HISTORY_LIMIT, min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity))
        )


@njit(cache=False, inline="always")
def _history_adjusted_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:
    base = _lmr_v3_reduction(depth, move_index)
    if history_score >= QUIET_HISTORY_LMR_THRESHOLD:
        return max(0, base - 1)
    if history_score <= -QUIET_HISTORY_LMR_THRESHOLD and depth >= 5 and move_index >= 4:
        return min(3, base + 1)
    return base


@njit(cache=False)
def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    side: int,
    previous_context: int,
    quiet_history: np.ndarray,
) -> None:
    """Stable one-pass ordering with learned scores only inside the ordinary-quiet band."""
    for index in range(count):
        move = int(moves[index])
        packed = _move_order_score_meta(board, move, preferred)
        score = packed >> 2
        meta = packed & 3
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            elif (meta & 2) == 0:
                context = _quiet_history_context(board, move)
                score += _quiet_history_score(side, previous_context, context, quiet_history)
        scores[index] = score * 4 + meta
    for index in range(1, count):
        move = int(moves[index])
        packed = int(scores[index])
        score = packed >> 2
        cursor = index - 1
        while cursor >= 0 and (int(scores[cursor]) >> 2) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = packed
'''
s = s[:start] + new_order + s[end:]

# Remove V15's separate LMR-only history helpers, retaining the base LMR schedule.
start = s.index('@njit(cache=False, inline="always")\ndef _lean_lmr_history_update(')
end = s.index('@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(', start)
s = s[:start] + s[end:]

# Search signatures: one history table plus per-ply move context in _negamax and _root.
old = '''    killers: np.ndarray,
    lmr_history: np.ndarray,
    hash_keys: np.ndarray,
'''
if s.count(old) != 2:
    raise SystemExit(f"search signature anchor count={s.count(old)}")
s = s.replace(
    old,
    '''    killers: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
    hash_keys: np.ndarray,
''',
)

# Negamax node setup and move ordering.
one(
    '''    alpha_original = alpha
    scout_node = beta == alpha + 1
''',
    '''    alpha_original = alpha
    scout_node = beta == alpha + 1
    previous_move_context = int(move_context_stack[ply - 1]) if ply > 0 else -1
''',
)
one(
    '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
''',
    '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
        side,
        previous_move_context,
        quiet_history,
    )
''',
)

# Replace per-move V15 LMR-history lookup with unified current+continuation lookup.
one(
    '''        moving_signed = int(board[move_from(move)])
        lmr_history_context = -1
        lmr_history_score = 0
        if quiet:
            lmr_history_context = (abs(moving_signed) - 1) * 64 + move_to(move)
            lmr_side_index = 0 if side == WHITE else 1
            lmr_history_score = int(lmr_history[lmr_side_index, lmr_history_context])
''',
    '''        moving_signed = int(board[move_from(move)])
        current_move_context = _quiet_history_context(board, move)
        move_context_stack[ply] = np.int16(current_move_context)
        move_history_score = (
            _quiet_history_score(side, previous_move_context, current_move_context, quiet_history)
            if quiet else 0
        )
''',
)
one(
    '''        reduction = (
            _lean_history_lmr_reduction(depth, index, lmr_history_score)
            if lmr_candidate else 0
        )
''',
    '''        reduction = (
            _history_adjusted_lmr_reduction(depth, index, move_history_score)
            if lmr_candidate else 0
        )
''',
)

# Recursive calls.
s = s.replace(
    'path_keys, killers, lmr_history, hash_keys, hash_moves, history_contexts, student_edges, tt_table,',
    'path_keys, killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges, tt_table,',
)

# Update coherent history after searched scout quiets; remove V15 table update.
one(
    '''        if quiet and scout_node and lmr_history_context >= 0:
            bonus = _lean_lmr_history_bonus(depth)
            requested = bonus if score >= beta else -(bonus // 2)
            lmr_side_index = 0 if side == WHITE else 1
            old_history = int(lmr_history[lmr_side_index, lmr_history_context])
            lmr_history[lmr_side_index, lmr_history_context] = _lean_lmr_history_update(
                old_history, requested
            )
''',
    '''        if quiet and scout_node:
            bonus = _quiet_history_depth_bonus(depth)
            requested = bonus if score >= beta else -(bonus // 2)
            _quiet_history_update(
                side, previous_move_context, current_move_context, requested, quiet_history
            )
''',
)

# Root move ordering and root->child continuation context.
one(
    '''    _order_moves(board, moves, count, preferred, score_stack[0])
''',
    '''    _order_moves_with_killers(
        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history
    )
''',
)
one(
    '''        move = int(moves[index])
        packed_order = int(score_stack[0, index])
        child_depth = depth - 1
''',
    '''        move = int(moves[index])
        packed_order = int(score_stack[0, index])
        move_context_stack[0] = np.int16(_quiet_history_context(board, move))
        child_depth = depth - 1
''',
)

# Allocations at each stateful entry point: replace the old LMR-only table.
old = '    lmr_history = np.zeros((2, 384), dtype=np.int16)\n'
count = s.count(old)
if count != 3:
    raise SystemExit(f"lmr allocation count={count}")
s = s.replace(
    old,
    '''    quiet_history = np.zeros(QUIET_HISTORY_STORAGE_SIZE, dtype=np.int16)
    move_context_stack = np.full(MAX_PLY, -1, dtype=np.int16)
''',
)

# Root calls from entry points.
s = s.replace(
    'killers, lmr_history, hash_keys, hash_moves, history_contexts, student_edges,',
    'killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,',
)
one(
    '''            path_keys,
            killers,
            lmr_history,
            hash_keys,
''',
    '''            path_keys,
            killers,
            quiet_history,
            move_context_stack,
            hash_keys,
''',
)

# Strong assertions against accidental dual-history remnants.
for token in ('LEAN_LMR_HISTORY_', '_lean_lmr_history_', '_lean_history_lmr_reduction', 'lmr_history'):
    if token in s:
        raise SystemExit(f"unified history patch left stale token {token!r}")
if s.count('quiet_history = np.zeros(QUIET_HISTORY_STORAGE_SIZE') != 3:
    raise SystemExit('unexpected quiet-history allocation count')
if s.count('move_context_stack = np.full(MAX_PLY') != 3:
    raise SystemExit('unexpected move-context allocation count')

p.write_text(s)
