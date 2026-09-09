#!/usr/bin/env python3
"""Port the confirmed Rust V15 quiet-history policy onto the V15 exact-speed stack.

This patch is intentionally compatible with the post-presort/post-scoremeta/post-lazy-H64 search:
move-order scores keep their two low metadata bits, while learned history changes only the high
ordering score.  The exact confirmed Rust-history semantics are retained:

* side-specific main history over (piece, destination),
* one-ply continuation history,
* stable history-aware quiet ordering behind PV/tacticals/killers,
* history-conditioned verified LMR,
* scout-node fail-high bonus / searched-fail-low malus with bounded gravity.

Apply after:
  patch_v15_python_presort_once.py
  patch_v15_python_lazy_h64_chain.py
  patch_v15_python_scoremeta_hotloop.py
(and independently after the fused H64 runtime patches).
"""
from __future__ import annotations

from pathlib import Path
import sys


def replace_exact(source: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    return source.replace(old, new, expected)


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v15_python_rust_history_speedstack.py numba_search.py")
    path = Path(sys.argv[1])
    s = path.read_text()
    if "QUIET_HISTORY_CONT_ENTRIES" in s:
        raise SystemExit("Rust history already present")

    # Same table geometry and gravity rule as the confirmed Rust->Python transfer.
    anchor = "TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\n"
    constants = '''TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1

# Exact Rust V15 quiet-history geometry: side-specific main history plus one-ply continuation.
QUIET_HISTORY_CONTEXTS = 6 * 64
QUIET_HISTORY_MAIN_ENTRIES = 2 * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_ENTRIES = QUIET_HISTORY_CONTEXTS * QUIET_HISTORY_CONTEXTS
QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES
QUIET_HISTORY_STORAGE_SIZE = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES
QUIET_HISTORY_LIMIT = 16_384
QUIET_HISTORY_MAX_UPDATE = 2_048
'''
    s = replace_exact(s, anchor, constants, "history constants")

    lmr_anchor = '''@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
'''
    helpers = '''@njit(cache=False, inline="always")
def _quiet_history_context(board: np.ndarray, move: int) -> int:
    piece = abs(int(board[move_from(move)]))
    return (piece - 1) * 64 + move_to(move)


@njit(cache=False, inline="always")
def _quiet_history_context_from_piece(moving_signed: int, move: int) -> int:
    return (abs(moving_signed) - 1) * 64 + move_to(move)


@njit(cache=False, inline="always")
def _quiet_history_score(side: int, previous: int, current: int, table: np.ndarray) -> int:
    side_index = 0 if side == WHITE else 1
    score = int(table[side_index * QUIET_HISTORY_CONTEXTS + current])
    if previous >= 0:
        score += int(
            table[QUIET_HISTORY_CONT_OFFSET + previous * QUIET_HISTORY_CONTEXTS + current]
        )
    return score


@njit(cache=False, inline="always")
def _quiet_history_depth_bonus(depth: int) -> int:
    return min(QUIET_HISTORY_MAX_UPDATE, 32 * depth * depth + 64 * depth)


@njit(cache=False, inline="always")
def _quiet_history_update(
    side: int,
    previous: int,
    current: int,
    requested_bonus: int,
    table: np.ndarray,
) -> None:
    bonus = max(-QUIET_HISTORY_MAX_UPDATE, min(QUIET_HISTORY_MAX_UPDATE, requested_bonus))
    side_index = 0 if side == WHITE else 1
    main_index = side_index * QUIET_HISTORY_CONTEXTS + current
    current_value = int(table[main_index])
    gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
    updated = max(
        -QUIET_HISTORY_LIMIT,
        min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity),
    )
    table[main_index] = np.int16(updated)
    if previous >= 0:
        cont_index = QUIET_HISTORY_CONT_OFFSET + previous * QUIET_HISTORY_CONTEXTS + current
        current_value = int(table[cont_index])
        gravity = trunc_div_scalar(current_value * abs(bonus), QUIET_HISTORY_LIMIT)
        updated = max(
            -QUIET_HISTORY_LIMIT,
            min(QUIET_HISTORY_LIMIT, current_value + bonus - gravity),
        )
        table[cont_index] = np.int16(updated)


@njit(cache=False, inline="always")
def _history_adjusted_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:
    base = _lmr_v3_reduction(depth, move_index)
    if history_score >= 4096:
        return max(0, base - 1)
    if history_score <= -4096 and depth >= 5 and move_index >= 4:
        return min(3, base + 1)
    return base


@njit(cache=False, inline="always")
def _lmr_v3_reduction(depth: int, move_index: int) -> int:
'''
    s = replace_exact(s, lmr_anchor, helpers, "LMR helper anchor")

    # Scoremeta has already converted the killer ordering pass to packed score*4 + metadata.
    old_order = '''@njit(cache=False)
def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
) -> None:
    """Order once while carrying tactical/pawn metadata in two low score bits."""
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
    new_order = '''@njit(cache=False)
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
    """Stable PV/tactical/killer ordering with Rust main+continuation history for quiets."""
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
    s = replace_exact(s, old_order, new_order, "scoremeta killer ordering")

    # Thread the two history arrays alongside the existing deferred-H64 edge array.
    neg_sig = '''    hash_moves: np.ndarray,
    history_contexts: np.ndarray,
    student_edges: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:'''
    neg_sig_new = '''    hash_moves: np.ndarray,
    history_contexts: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
    student_edges: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:'''
    s = replace_exact(s, neg_sig, neg_sig_new, "negamax signature")
    root_sig = neg_sig.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
    root_sig_new = neg_sig_new.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
    s = replace_exact(s, root_sig, root_sig_new, "root signature")

    s = replace_exact(
        s,
        '''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
''',
        '''    alpha_original = alpha
    node_null_window = beta == alpha + 1
    pseudo = pseudo_stack[ply]
''',
        "scout-node marker",
    )

    # Ordinary-node move ordering: preserve scoremeta packing, add prior-move continuation context.
    old_call = '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
'''
    new_call = '''    previous_move_context = int(move_context_stack[ply - 1]) if ply > 0 else -1
    _order_moves_with_killers(
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
'''
    s = replace_exact(s, old_call, new_call, "negamax history ordering")

    # The lazy-H64 patch already loads moving_signed once before make.  Reuse it for history context.
    old_move = '''        moving_signed = int(board[move_from(move)])
        _advance_eval_state_into(
'''
    new_move = '''        moving_signed = int(board[move_from(move)])
        current_move_context = _quiet_history_context_from_piece(moving_signed, move)
        move_context_stack[ply] = np.int16(current_move_context)
        _advance_eval_state_into(
'''
    s = replace_exact(s, old_move, new_move, "move context reuse")

    old_lmr = '''        lmr_candidate = not checked and quiet and not protected_killer
        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0
'''
    new_lmr = '''        lmr_candidate = not checked and quiet and not protected_killer
        move_history_score = _quiet_history_score(
            side, previous_move_context, current_move_context, quiet_history
        )
        reduction = (
            _history_adjusted_lmr_reduction(depth, index, move_history_score)
            if lmr_candidate else 0
        )
'''
    s = replace_exact(s, old_lmr, new_lmr, "history-adjusted LMR")

    old_update = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
'''
    new_update = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if quiet and node_null_window:
            history_bonus = _quiet_history_depth_bonus(depth)
            history_update = history_bonus if score >= beta else -(history_bonus // 2)
            _quiet_history_update(
                side,
                previous_move_context,
                current_move_context,
                history_update,
                quiet_history,
            )
        if score > best_score:
'''
    s = replace_exact(s, old_update, new_update, "history training")

    # Root ordering uses the same learned quiet score.  Scoremeta's root low bits remain intact.
    s = replace_exact(
        s,
        '''    _order_moves(board, moves, count, preferred, score_stack[0])
''',
        '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[0],
        -1,
        -1,
        side,
        -1,
        quiet_history,
    )
''',
        "root history ordering",
    )
    s = replace_exact(
        s,
        '''        move = int(moves[index])
        packed_order = int(score_stack[0, index])
        child_depth = depth - 1
''',
        '''        move = int(moves[index])
        packed_order = int(score_stack[0, index])
        move_context_stack[0] = np.int16(_quiet_history_context(board, move))
        child_depth = depth - 1
''',
        "root move context",
    )

    # Recursive compact tails created by the lazy-H64 patch.
    compact = '''path_keys, killers, hash_keys, hash_moves, history_contexts, student_edges, tt_table,'''
    compact_new = '''path_keys, killers, hash_keys, hash_moves, history_contexts, quiet_history, move_context_stack, student_edges, tt_table,'''
    compact_count = s.count(compact)
    if compact_count < 7:
        raise SystemExit(f"recursive call tails: suspicious count {compact_count}")
    s = s.replace(compact, compact_new)

    # Public entrypoint root calls may be vertically expanded or split compactly.
    expanded = '''            hash_moves,
            history_contexts,
            student_edges,
            tt_table,
'''
    expanded_new = '''            hash_moves,
            history_contexts,
            quiet_history,
            move_context_stack,
            student_edges,
            tt_table,
'''
    if expanded in s:
        s = s.replace(expanded, expanded_new)
    compact_root = '''            killers, hash_keys, hash_moves, history_contexts, student_edges,
            tt_table,
'''
    compact_root_new = '''            killers, hash_keys, hash_moves, history_contexts, quiet_history, move_context_stack, student_edges,
            tt_table,
'''
    if compact_root in s:
        s = s.replace(compact_root, compact_root_new)

    # One table per public search call; it persists across iterative-deepening depths exactly as in
    # the confirmed transfer.  Allocation is outside recursive search.
    allocation = '''    student_edges = np.zeros(MAX_PLY, dtype=np.uint64)
'''
    allocation_new = '''    quiet_history = np.zeros(QUIET_HISTORY_STORAGE_SIZE, dtype=np.int16)
    move_context_stack = np.full(MAX_PLY, -1, dtype=np.int16)
    student_edges = np.zeros(MAX_PLY, dtype=np.uint64)
'''
    alloc_count = s.count(allocation)
    if alloc_count != 3:
        raise SystemExit(f"history allocation: expected 3, found {alloc_count}")
    s = s.replace(allocation, allocation_new)

    # Structural sanity: every deferred-H64 root/recursive call must now carry both history arrays.
    if compact in s:
        raise SystemExit("old recursive tail remains")
    if "history_contexts, student_edges, tt_table" in s:
        raise SystemExit("old compact history/student tail remains")
    if s.count("QUIET_HISTORY_CONT_ENTRIES") != 2:  # declaration + storage expression
        raise SystemExit("history constants were not installed as expected")

    path.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
