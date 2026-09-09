#!/usr/bin/env python3
"""Add the compact t2048 LMR-confidence policy to a leaf-only Gestalt search.

This is the no-student-edge sibling of patch_v15_python_lean_lmr_history.py.  It keeps move
ordering and evaluation untouched: one 2x384 int16 table records quiet scout-node evidence and is
used only to make verified LMR one ply milder for strongly trusted quiets or one ply harsher for
strongly bad late quiets.

Apply after presort + scoremeta + leaf Gestalt materialization.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def exact(s: str, old: str, new: str, label: str, n: int = 1) -> str:
    c = s.count(old)
    if c != n:
        raise SystemExit(f"{label}: expected {n}, found {c}")
    return s.replace(old, new, n)


def patch(path: Path, threshold: int) -> None:
    if not 0 < threshold < 16384:
        raise SystemExit("threshold must be in 1..16383")
    s = path.read_text()
    if "LEAN_LMR_HISTORY_LIMIT" in s:
        raise SystemExit("lean LMR history already present")
    if "student_edges" in s:
        raise SystemExit("leaf/no-student patch received a student-edge search")

    s = exact(
        s,
        "MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n",
        f"""MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n\nLEAN_LMR_HISTORY_LIMIT = 16_384\nLEAN_LMR_HISTORY_MAX_UPDATE = 2_048\nLEAN_LMR_HISTORY_THRESHOLD = {threshold}\n""",
        "constants",
    )

    anchor = '''@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n'''
    helpers = '''@njit(cache=False, inline="always")\ndef _lean_lmr_history_update(current: int, requested_bonus: int) -> int:\n    bonus = max(-LEAN_LMR_HISTORY_MAX_UPDATE, min(LEAN_LMR_HISTORY_MAX_UPDATE, requested_bonus))\n    product = current * abs(bonus)\n    gravity = product // LEAN_LMR_HISTORY_LIMIT if product >= 0 else -((-product) // LEAN_LMR_HISTORY_LIMIT)\n    return max(-LEAN_LMR_HISTORY_LIMIT, min(LEAN_LMR_HISTORY_LIMIT, current + bonus - gravity))\n\n\n@njit(cache=False, inline="always")\ndef _lean_lmr_history_bonus(depth: int) -> int:\n    return min(LEAN_LMR_HISTORY_MAX_UPDATE, 32 * depth * depth + 64 * depth)\n\n\n@njit(cache=False, inline="always")\ndef _lean_history_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:\n    base = _lmr_v3_reduction(depth, move_index)\n    if history_score >= LEAN_LMR_HISTORY_THRESHOLD:\n        return max(0, base - 1)\n    if history_score <= -LEAN_LMR_HISTORY_THRESHOLD and depth >= 5 and move_index >= 4:\n        return min(3, base + 1)\n    return base\n\n\n@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n'''
    s = exact(s, anchor, helpers, "LMR helpers")

    sig = '''    path_keys: np.ndarray,\n    killers: np.ndarray,\n    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
    sig2 = '''    path_keys: np.ndarray,\n    killers: np.ndarray,\n    lmr_history: np.ndarray,\n    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
    s = exact(s, sig, sig2, "negamax signature")
    s = exact(
        s,
        sig.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:"),
        sig2.replace(") -> tuple[int, bool]:", ") -> tuple[int, int, bool]:"),
        "root signature",
    )

    s = exact(
        s,
        '''    alpha_original = alpha\n    pseudo = pseudo_stack[ply]\n''',
        '''    alpha_original = alpha\n    scout_node = beta == alpha + 1\n    pseudo = pseudo_stack[ply]\n''',
        "scout marker",
    )

    move_anchor = '''        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n'''
    move_new = '''        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        lmr_history_context = -1\n        lmr_history_score = 0\n        if quiet:\n            moving_signed = int(board[move_from(move)])\n            lmr_history_context = (abs(moving_signed) - 1) * 64 + move_to(move)\n            lmr_side_index = 0 if side == WHITE else 1\n            lmr_history_score = int(lmr_history[lmr_side_index, lmr_history_context])\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n'''
    s = exact(s, move_anchor, move_new, "move confidence context")

    s = exact(
        s,
        '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0\n''',
        '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = (\n            _lean_history_lmr_reduction(depth, index, lmr_history_score)\n            if lmr_candidate else 0\n        )\n''',
        "LMR coupling",
    )

    s = exact(
        s,
        '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if score > best_score:\n''',
        '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if quiet and scout_node and lmr_history_context >= 0:\n            bonus = _lean_lmr_history_bonus(depth)\n            requested = bonus if score >= beta else -(bonus // 2)\n            lmr_side_index = 0 if side == WHITE else 1\n            old_history = int(lmr_history[lmr_side_index, lmr_history_context])\n            lmr_history[lmr_side_index, lmr_history_context] = _lean_lmr_history_update(old_history, requested)\n        if score > best_score:\n''',
        "history update",
    )

    old_tail = '''path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,'''
    new_tail = '''path_keys, killers, lmr_history, hash_keys, hash_moves, history_contexts, tt_table,'''
    c = s.count(old_tail)
    if c < 5:
        raise SystemExit(f"recursive/root compact tails: suspicious count {c}")
    s = s.replace(old_tail, new_tail)

    expanded = '''            path_keys,\n            killers,\n            hash_keys,\n            hash_moves,\n            history_contexts,\n            tt_table,\n'''
    expanded_new = '''            path_keys,\n            killers,\n            lmr_history,\n            hash_keys,\n            hash_moves,\n            history_contexts,\n            tt_table,\n'''
    if expanded in s:
        s = s.replace(expanded, expanded_new)

    compact_root = '''            killers, hash_keys, hash_moves, history_contexts,\n            tt_table,\n'''
    compact_root_new = '''            killers, lmr_history, hash_keys, hash_moves, history_contexts,\n            tt_table,\n'''
    if compact_root in s:
        s = s.replace(compact_root, compact_root_new)

    alloc = '''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)\n'''
    alloc_new = alloc + '''    lmr_history = np.zeros((2, 384), dtype=np.int16)\n'''
    if s.count(alloc) != 3:
        raise SystemExit(f"history allocation: expected 3, found {s.count(alloc)}")
    s = s.replace(alloc, alloc_new)

    if old_tail in s:
        raise SystemExit("unpatched recursive tail remains")
    if s.count("def _negamax(") != 1 or s.count("def _root(") != 1:
        raise SystemExit("search structure changed unexpectedly")
    path.write_text(s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("path", type=Path)
    ap.add_argument("--threshold", type=int, default=2048)
    a = ap.parse_args()
    patch(a.path, a.threshold)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
