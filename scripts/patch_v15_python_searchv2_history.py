#!/usr/bin/env python3
"""Port the accepted Rust Search-v2 history/LMR coupling onto exact packaged Python V14.

This is intentionally a coherent stack rather than the earlier main-history-only experiment:
side-specific main history + one-ply continuation history score ordinary quiets, the same score
conditions verified LMR, and scout-node evidence updates both tables with the accepted bounded
gravity rule. Tables live for one top-level search so iterative deepening can teach later depths
without leaking state across game moves.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()


def rep(old: str, new: str, n: int = 1, label: str = "") -> None:
    global s
    count = s.count(old)
    if count != n:
        raise SystemExit(f"{label or old[:30]} count={count} expected={n}")
    s = s.replace(old, new, n)


anchor = "MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n"
insert = """MAX_PLY = MAX_DEPTH + MAX_QPLY + 4

# V15 Search-v2 history substrate, ported from the accepted Rust stack.
MOVE_CONTEXTS = 6 * 64
HISTORY_LIMIT = 16_384
HISTORY_MAX_UPDATE = 2_048
"""
rep(anchor, insert, label="constants")

anchor = '''@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
'''
helpers = '''@njit(cache=False, inline="always")
def _move_history_context(board: np.ndarray, move: int) -> int:
    # Python piece ids are Pawn=1 .. King=6, matching Rust PieceKind ordering after -1.
    piece_index = abs(int(board[move_from(move)])) - 1
    return piece_index * 64 + move_to(move)


@njit(cache=False, inline="always")
def _history_score(
    side: int,
    previous_context: int,
    current_context: int,
    main_history: np.ndarray,
    continuation_history: np.ndarray,
) -> int:
    side_index = 0 if side == WHITE else 1
    score = int(main_history[side_index, current_context])
    if previous_context >= 0:
        score += int(continuation_history[previous_context, current_context])
    return score


@njit(cache=False, inline="always")
def _history_update_entry(current: int, requested_bonus: int) -> int:
    bonus = max(-HISTORY_MAX_UPDATE, min(HISTORY_MAX_UPDATE, requested_bonus))
    gravity = current * abs(bonus) // HISTORY_LIMIT
    return max(-HISTORY_LIMIT, min(HISTORY_LIMIT, current + bonus - gravity))


@njit(cache=False, inline="always")
def _update_quiet_history(
    side: int,
    previous_context: int,
    current_context: int,
    bonus: int,
    main_history: np.ndarray,
    continuation_history: np.ndarray,
) -> None:
    side_index = 0 if side == WHITE else 1
    old = int(main_history[side_index, current_context])
    main_history[side_index, current_context] = _history_update_entry(old, bonus)
    if previous_context >= 0:
        old = int(continuation_history[previous_context, current_context])
        continuation_history[previous_context, current_context] = _history_update_entry(old, bonus)


@njit(cache=False, inline="always")
def _history_depth_bonus(depth: int) -> int:
    return min(HISTORY_MAX_UPDATE, 32 * depth * depth + 64 * depth)


@njit(cache=False, inline="always")
def _history_adjusted_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:
    base = _lmr_v3_reduction(depth, move_index)
    if history_score >= 4_096:
        return max(0, base - 1)
    if history_score <= -4_096 and depth >= 5 and move_index >= 4:
        return min(3, base + 1)
    return base


@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
'''
rep(anchor, helpers, label="history helpers")

old = '''def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
) -> None:
    """Order PV/tacticals first, then two quiet killers, then ordinary quiets."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
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
rep(old, new, label="order helper")

marker = '''        scores[index] = score



@njit(cache=False)
def _is_tactical'''
roothelper = '''        scores[index] = score


@njit(cache=False)
def _order_root_moves_with_history(
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



@njit(cache=False)
def _is_tactical'''
rep(marker, roothelper, label="root order helper")

old = '''    path_keys: np.ndarray,
    killers: np.ndarray,
    hash_keys: np.ndarray,
    hash_moves: np.ndarray,
    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:'''
new = '''    path_keys: np.ndarray,
    killers: np.ndarray,
    main_history: np.ndarray,
    continuation_history: np.ndarray,
    move_contexts: np.ndarray,
    hash_keys: np.ndarray,
    hash_moves: np.ndarray,
    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:'''
rep(old, new, label="negamax signature")
old_root = old.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
new_root = new.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
rep(old_root, new_root, label="root signature")

old = '''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
'''
new = '''    alpha_original = alpha
    scout_node = beta == alpha + 1
    previous_move_context = int(move_contexts[ply - 1]) if ply > 0 else -1
    pseudo = pseudo_stack[ply]
'''
rep(old, new, label="scout context")

old = '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
'''
new = '''    _order_moves_with_killers(
        board,
        side,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
        previous_move_context,
        main_history,
        continuation_history,
    )
'''
rep(old, new, label="order call")

old = '''        quiet = not _is_tactical(board, move)
        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
new = '''        quiet = not _is_tactical(board, move)
        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
        move_context = _move_history_context(board, move)
        move_contexts[ply] = move_context
        move_history_score = _history_score(
            side, previous_move_context, move_context, main_history, continuation_history
        )
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
rep(old, new, label="move context")

old = '''        lmr_candidate = not checked and quiet and not protected_killer
        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0
'''
new = '''        lmr_candidate = not checked and quiet and not protected_killer
        reduction = (
            _history_adjusted_lmr_reduction(depth, index, move_history_score)
            if lmr_candidate else 0
        )
'''
rep(old, new, label="LMR adjust")

old = '''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,
'''
new = '''                path_keys, killers, main_history, continuation_history, move_contexts,
                hash_keys, hash_moves, history_contexts, tt_table,
'''
rep(old, new, n=7, label="negamax call tails")

old = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
'''
new = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)

        # Match accepted Rust Search-v2: train exactly once from final scout-node evidence.
        if quiet and scout_node:
            bonus = _history_depth_bonus(depth)
            update = bonus if score >= beta else -(bonus // 2)
            _update_quiet_history(
                side, previous_move_context, move_context, update,
                main_history, continuation_history,
            )

        if score > best_score:
'''
rep(old, new, label="history train")

old = '''    _order_moves(board, moves, count, preferred, score_stack[0])
'''
new = '''    _order_root_moves_with_history(
        board, side, moves, count, preferred, score_stack[0], main_history
    )
'''
rep(old, new, label="root ordering")
old = '''        move = int(moves[index])
        child_depth = depth - 1
'''
new = '''        move = int(moves[index])
        move_contexts[0] = _move_history_context(board, move)
        child_depth = depth - 1
'''
rep(old, new, label="root move context")

old = '''            path_keys,
            killers,
            hash_keys,
            hash_moves,
            history_contexts,
            tt_table,
'''
new = '''            path_keys,
            killers,
            main_history,
            continuation_history,
            move_contexts,
            hash_keys,
            hash_moves,
            history_contexts,
            tt_table,
'''
s = s.replace(old, new)

old = '''            killers, hash_keys, hash_moves, history_contexts,
            tt_table,
'''
new = '''            killers, main_history, continuation_history, move_contexts,
            hash_keys, hash_moves, history_contexts, tt_table,
'''
s = s.replace(old, new)

alloc = '''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
'''
replacement = '''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
    main_history = np.zeros((2, MOVE_CONTEXTS), dtype=np.int16)
    continuation_history = np.zeros((MOVE_CONTEXTS, MOVE_CONTEXTS), dtype=np.int16)
    move_contexts = np.full(MAX_PLY, -1, dtype=np.int16)
'''
rep(alloc, replacement, n=3, label="history allocations")

if s.count("def _root(") != 1 or s.count("def _negamax(") != 1:
    raise SystemExit("function structure changed")
if "path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table" in s:
    raise SystemExit("old recursive call tail remains")

p.write_text(s)
