#!/usr/bin/env python3
"""Add a compact Search-v2-style confidence signal used only to modulate verified LMR.

This deliberately does *not* use history for move ordering.  The earlier Python main-history
ordering experiment failed replication, while the coherent Rust Search-v2 transfer showed a small
but repeatable equal-node tree-efficiency gain and paid most of its runtime cost for a large
continuation-history substrate.  Here we retain only the high-value coupling:

  * one tiny side x (piece,to-square) int16 table (2 x 384 entries),
  * scout-node quiet evidence updates it with bounded gravity,
  * strongly good late quiets are reduced one ply less,
  * strongly bad late quiets may be reduced one ply more,
  * ordering, qsearch, evaluation, TT and all verification searches remain unchanged.

Apply after the V15 exact-speed stack (presort, fused/lazy H64 and score metadata).
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_exact(source: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    return source.replace(old, new, expected)


def patch(path: Path, threshold: int) -> None:
    s = path.read_text()
    if "LEAN_LMR_HISTORY_LIMIT" in s:
        raise SystemExit("lean LMR history already present")
    if threshold <= 0 or threshold >= 16_384:
        raise SystemExit("threshold must be in 1..16383")

    # Small fixed substrate.  Main-history-only means the threshold is intentionally lower than the
    # 4096 combined main+continuation threshold used by the old coherent transfer.
    anchor = "MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n"
    constants = f'''MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n\n# Lean Search-v2 LMR confidence.  Never participates in move ordering.\nLEAN_LMR_HISTORY_LIMIT = 16_384\nLEAN_LMR_HISTORY_MAX_UPDATE = 2_048\nLEAN_LMR_HISTORY_THRESHOLD = {threshold}\n'''
    s = replace_exact(s, anchor, constants, "constants")

    anchor = '''@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n'''
    helpers = '''@njit(cache=False, inline="always")\ndef _lean_lmr_history_update(current: int, requested_bonus: int) -> int:\n    bonus = max(-LEAN_LMR_HISTORY_MAX_UPDATE, min(LEAN_LMR_HISTORY_MAX_UPDATE, requested_bonus))\n    product = current * abs(bonus)\n    # Match Rust signed division: truncate toward zero rather than Python floor for negatives.\n    gravity = product // LEAN_LMR_HISTORY_LIMIT if product >= 0 else -((-product) // LEAN_LMR_HISTORY_LIMIT)\n    return max(\n        -LEAN_LMR_HISTORY_LIMIT,\n        min(LEAN_LMR_HISTORY_LIMIT, current + bonus - gravity),\n    )\n\n\n@njit(cache=False, inline="always")\ndef _lean_lmr_history_bonus(depth: int) -> int:\n    return min(LEAN_LMR_HISTORY_MAX_UPDATE, 32 * depth * depth + 64 * depth)\n\n\n@njit(cache=False, inline="always")\ndef _lean_history_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:\n    base = _lmr_v3_reduction(depth, move_index)\n    if history_score >= LEAN_LMR_HISTORY_THRESHOLD:\n        return max(0, base - 1)\n    if history_score <= -LEAN_LMR_HISTORY_THRESHOLD and depth >= 5 and move_index >= 4:\n        return min(3, base + 1)\n    return base\n\n\n@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n'''
    s = replace_exact(s, anchor, helpers, "LMR helper anchor")

    # Thread one tiny table through _negamax and _root.  The exact-speed stack has student_edges
    # immediately before TT; keeping history beside killers minimizes churn in all recursive tails.
    sig = '''    path_keys: np.ndarray,\n    killers: np.ndarray,\n    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
    sig_new = '''    path_keys: np.ndarray,\n    killers: np.ndarray,\n    lmr_history: np.ndarray,\n    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
    s = replace_exact(s, sig, sig_new, "negamax signature")
    root_sig = sig.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
    root_sig_new = sig_new.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:")
    s = replace_exact(s, root_sig, root_sig_new, "root signature")

    # We train only on null-window (scout) evidence, matching the accepted Search-v2 semantics.
    old = '''    alpha_original = alpha\n    pseudo = pseudo_stack[ply]\n'''
    new = '''    alpha_original = alpha\n    scout_node = beta == alpha + 1\n    pseudo = pseudo_stack[ply]\n'''
    s = replace_exact(s, old, new, "scout-node marker")

    # The lazy-H64 stack already loads moving_signed before making the move.  Reuse that one load to
    # index piece-destination history; no from-square table and no continuation context are needed.
    old = '''        moving_signed = int(board[move_from(move)])\n        _advance_eval_state_into(\n'''
    new = '''        moving_signed = int(board[move_from(move)])\n        lmr_history_context = -1\n        lmr_history_score = 0\n        if quiet:\n            lmr_history_context = (abs(moving_signed) - 1) * 64 + move_to(move)\n            lmr_side_index = 0 if side == WHITE else 1\n            lmr_history_score = int(lmr_history[lmr_side_index, lmr_history_context])\n        _advance_eval_state_into(\n'''
    s = replace_exact(s, old, new, "move history context")

    old = '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0\n'''
    new = '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = (\n            _lean_history_lmr_reduction(depth, index, lmr_history_score)\n            if lmr_candidate else 0\n        )\n'''
    s = replace_exact(s, old, new, "LMR coupling")

    # Train only moves that were actually searched.  Futility-skipped quiets continue before this
    # point and therefore cannot poison the confidence table with fabricated evidence.
    old = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if score > best_score:\n'''
    new = '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if quiet and scout_node and lmr_history_context >= 0:\n            bonus = _lean_lmr_history_bonus(depth)\n            requested = bonus if score >= beta else -(bonus // 2)\n            lmr_side_index = 0 if side == WHITE else 1\n            old_history = int(lmr_history[lmr_side_index, lmr_history_context])\n            lmr_history[lmr_side_index, lmr_history_context] = _lean_lmr_history_update(\n                old_history, requested\n            )\n        if score > best_score:\n'''
    s = replace_exact(s, old, new, "history training")

    # Compact recursive/root tails.
    compact = '''path_keys, killers, hash_keys, hash_moves, history_contexts, student_edges, tt_table,'''
    compact_new = '''path_keys, killers, lmr_history, hash_keys, hash_moves, history_contexts, student_edges, tt_table,'''
    compact_count = s.count(compact)
    if compact_count < 5:
        raise SystemExit(f"compact recursive tails: suspicious count {compact_count}")
    s = s.replace(compact, compact_new)

    # Expanded public-entry root call.
    expanded = '''            path_keys,\n            killers,\n            hash_keys,\n            hash_moves,\n            history_contexts,\n            student_edges,\n            tt_table,\n'''
    expanded_new = '''            path_keys,\n            killers,\n            lmr_history,\n            hash_keys,\n            hash_moves,\n            history_contexts,\n            student_edges,\n            tt_table,\n'''
    expanded_count = s.count(expanded)
    if expanded_count:
        s = s.replace(expanded, expanded_new)

    # Some adaptive/timed public entrypoints format the root tail compactly across two lines.
    compact_root = '''            killers, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n'''
    compact_root_new = '''            killers, lmr_history, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n'''
    if compact_root in s:
        s = s.replace(compact_root, compact_root_new)

    allocation = '''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)\n'''
    allocation_new = allocation + '''    lmr_history = np.zeros((2, 384), dtype=np.int16)\n'''
    alloc_count = s.count(allocation)
    if alloc_count != 3:
        raise SystemExit(f"history allocation: expected 3, found {alloc_count}")
    s = s.replace(allocation, allocation_new)

    # Fail loudly if a call site still has the old tail or if the patch accidentally touched order.
    if compact in s:
        raise SystemExit("old recursive tail remains")
    if s.count("def _negamax(") != 1 or s.count("def _root(") != 1:
        raise SystemExit("search function structure changed")
    if "_order_moves_with_killers(\n        board,\n        side," in s:
        raise SystemExit("unexpected history-aware ordering present")

    path.write_text(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--threshold", type=int, default=2048)
    args = parser.parse_args()
    patch(args.path, args.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
