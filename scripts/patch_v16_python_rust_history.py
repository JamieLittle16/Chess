#!/usr/bin/env python3
from pathlib import Path
import re, sys
p=Path(sys.argv[1]); s=p.read_text()

anchor='TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\n'
insert='''TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1

# Exact Rust V15 quiet-history geometry: side-specific main history plus one-ply continuation.
QUIET_HISTORY_CONTEXTS = 6 * 64
QUIET_HISTORY_MAIN_ENTRIES = 2 * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_ENTRIES = QUIET_HISTORY_CONTEXTS * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES
QUIET_HISTORY_STORAGE_SIZE = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES
QUIET_HISTORY_LIMIT = 16_384
QUIET_HISTORY_MAX_UPDATE = 2_048
'''
assert s.count(anchor)==1, s.count(anchor)
s=s.replace(anchor,insert,1)

start=s.index('@njit(cache=False)\ndef _order_moves_with_killers(')
end=s.index('\n\n@njit(cache=False)\ndef _is_tactical', start)
new='''@njit(cache=False, inline="always")
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
    bonus = 32 * depth * depth + 64 * depth
    return min(QUIET_HISTORY_MAX_UPDATE, bonus)


@njit(cache=False, inline="always")
def _quiet_history_update(side: int, previous: int, current: int, requested_bonus: int, table: np.ndarray) -> None:
    bonus = max(-QUIET_HISTORY_MAX_UPDATE, min(QUIET_HISTORY_MAX_UPDATE, requested_bonus))
    side_index = 0 if side == WHITE else 1
    main_index = side_index * QUIET_HISTORY_CONTEXTS + current
    current_value = int(table[main_index])
    gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
    updated = max(-QUIET_HISTORY_LIMIT, min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity))
    table[main_index] = np.int16(updated)
    if previous >= 0:
        cont_index = QUIET_HISTORY_CONT_OFFSET + previous * QUIET_HISTORY_CONTEXTS + current
        current_value = int(table[cont_index])
        gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
        updated = max(-QUIET_HISTORY_LIMIT, min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity))
        table[cont_index] = np.int16(updated)


@njit(cache=False, inline="always")
def _history_adjusted_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:
    base = _lmr_v3_reduction(depth, move_index)
    if history_score >= 4096:
        return max(0, base - 1)
    if history_score <= -4096 and depth >= 5 and move_index >= 4:
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
    """Order PV/tacticals, killers, then learned ordinary quiets in one stable pass."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            else:
                context = _quiet_history_context(board, move)
                score += _quiet_history_score(side, previous_context, context, quiet_history)
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
s=s[:start]+new+s[end:]

old='''    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:'''
new_sig='''    history_contexts: np.ndarray,
    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
) -> tuple[int, bool]:'''
assert s.count(old)==1, s.count(old)
s=s.replace(old,new_sig,1)
old='''    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, int, bool]:'''
new_sig='''    history_contexts: np.ndarray,
    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
) -> tuple[int, int, bool]:'''
assert s.count(old)==1, s.count(old)
s=s.replace(old,new_sig,1)

s=re.sub(r'history_contexts,\s*tt_table,', 'history_contexts, tt_table, quiet_history, move_context_stack,', s)

old='''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
'''
new='''    previous_context = int(move_context_stack[ply - 1]) if ply > 0 else -1
    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
        side,
        previous_context,
        quiet_history,
    )
'''
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

old='''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
'''
new='''    alpha_original = alpha
    node_null_window = beta == alpha + 1
    pseudo = pseudo_stack[ply]
'''
assert s.count(old)==1
s=s.replace(old,new,1)

old='''        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
new='''        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
        current_move_context = _quiet_history_context(board, move)
        move_context_stack[ply] = np.int16(current_move_context)
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
assert s.count(old)==1
s=s.replace(old,new,1)

old='''        lmr_candidate = not checked and quiet and not protected_killer
        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0
'''
new='''        lmr_candidate = not checked and quiet and not protected_killer
        move_history_score = _quiet_history_score(side, previous_context, current_move_context, quiet_history)
        reduction = _history_adjusted_lmr_reduction(depth, index, move_history_score) if lmr_candidate else 0
'''
assert s.count(old)==1
s=s.replace(old,new,1)

old='''        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
'''
new='''        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if quiet and node_null_window:
            history_bonus = _quiet_history_depth_bonus(depth)
            history_update = history_bonus if score >= beta else -(history_bonus // 2)
            _quiet_history_update(side, previous_context, current_move_context, history_update, quiet_history)
        if score > best_score:
'''
assert s.count(old)==1, s.count(old)
s=s.replace(old,new,1)

old='''    _order_moves(board, moves, count, preferred, score_stack[0])
'''
new='''    _order_moves_with_killers(
        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history
    )
'''
assert s.count(old)==1
s=s.replace(old,new,1)
old='''        move = int(moves[index])
        child_depth = depth - 1
'''
new='''        move = int(moves[index])
        move_context_stack[0] = np.int16(_quiet_history_context(board, move))
        child_depth = depth - 1
'''
assert s.count(old)==1
s=s.replace(old,new,1)

s=s.replace('        _pick_next_scored_move(moves, score_stack[ply], index, count)\n','')
s=s.replace('        _pick_next_scored_move(moves, score_stack[0], index, count)\n','')

alloc='''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
'''
replacement='''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
    quiet_history = np.zeros(QUIET_HISTORY_STORAGE_SIZE, dtype=np.int16)
    move_context_stack = np.full(MAX_PLY, -1, dtype=np.int16)
'''
count=s.count(alloc)
assert count==3, count
s=s.replace(alloc,replacement)

s=s.replace('''            killers, hash_keys, hash_moves, history_contexts, tt_table,
        )''','''            killers, hash_keys, hash_moves, history_contexts, tt_table, quiet_history, move_context_stack,
        )''')
s=s.replace('''            killers, hash_keys, hash_moves, history_contexts,
            tt_table,
        )''','''            killers, hash_keys, hash_moves, history_contexts,
            tt_table, quiet_history, move_context_stack,
        )''')
if 'tt_table,\n        )' in s:
    raise SystemExit('unpatched tt_table call tail remains')

p.write_text(s)
