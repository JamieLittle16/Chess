#!/usr/bin/env python3
"""Apply the V18 root-score-recycling experiment to an extracted numba_search.py."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    def rep(old: str, new: str, count: int = 1) -> None:
        nonlocal s
        actual = s.count(old)
        if actual != count:
            raise RuntimeError(f"patch anchor count {actual} != {count}: {old[:100]!r}")
        s = s.replace(old, new, count)

    rep(
        """    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:""",
        """    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    previous_root_moves: np.ndarray,\n    previous_root_scores: np.ndarray,\n    root_score_scratch_moves: np.ndarray,\n    root_score_scratch_scores: np.ndarray,\n    previous_root_valid: int,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:""",
    )
    rep(
        """    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)""",
        """    _order_moves_with_killers(\n        board, moves, count, preferred, score_stack[0], -1, -1, side, -1, quiet_history\n    )\n    # Recycle the complete previous iteration's root ranking. The preferred/PV move stays first;\n    # all other roots are ordered by the exact score already paid for one ply shallower.\n    if previous_root_valid != 0:\n        for recycle_i in range(count):\n            recycle_move = int(moves[recycle_i])\n            if recycle_move == preferred:\n                continue\n            old_packed = int(score_stack[0, recycle_i])\n            old_meta = old_packed & 3\n            old_score = old_packed >> 2\n            for recycle_j in range(count):\n                if int(previous_root_moves[recycle_j]) == recycle_move:\n                    prior_score = int(previous_root_scores[recycle_j])\n                    if prior_score > 20_000:\n                        prior_score = 20_000\n                    elif prior_score < -20_000:\n                        prior_score = -20_000\n                    tie_break = old_score // 100_000\n                    score_stack[0, recycle_i] = (8_000_000 + prior_score * 32 + tie_break) * 4 + old_meta\n                    break\n\n    _pick_next_scored_move(moves, score_stack[0], 0, count)""",
    )
    rep(
        """        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        if score > best_score:""",
        """        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        root_score_scratch_moves[index] = move\n        root_score_scratch_scores[index] = score\n        if score > best_score:""",
    )

    arrays = """    previous_root_moves = np.full(MAX_MOVES, -1, dtype=np.int32)\n    previous_root_scores = np.full(MAX_MOVES, -INFINITY, dtype=np.int32)\n    root_score_scratch_moves = np.full(MAX_MOVES, -1, dtype=np.int32)\n    root_score_scratch_scores = np.full(MAX_MOVES, -INFINITY, dtype=np.int32)\n    previous_root_valid = 0\n"""
    rep(
        """    completed_depth = 0\n    nodes = np.zeros(1, dtype=np.int64)\n    hard_deadline_ticks = 0""",
        """    completed_depth = 0\n    nodes = np.zeros(1, dtype=np.int64)\n""" + arrays + """    hard_deadline_ticks = 0""",
    )
    rep(
        """    completed_depth = 0\n    nodes = np.zeros(1, dtype=np.int64)\n    previous_move = -1""",
        """    completed_depth = 0\n    nodes = np.zeros(1, dtype=np.int64)\n""" + arrays + """    previous_move = -1""",
        2,
    )
    rep(
        """            killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,""",
        """            killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts,\n            previous_root_moves, previous_root_scores, root_score_scratch_moves, root_score_scratch_scores, previous_root_valid,\n            student_edges, tt_table,""",
        2,
    )
    rep(
        """            hash_keys,\n            hash_moves,\n            history_contexts,\n            student_edges,\n            tt_table,""",
        """            hash_keys,\n            hash_moves,\n            history_contexts,\n            previous_root_moves,\n            previous_root_scores,\n            root_score_scratch_moves,\n            root_score_scratch_scores,\n            previous_root_valid,\n            student_edges,\n            tt_table,""",
    )
    copy = """        for recycle_i in range(count):\n            previous_root_moves[recycle_i] = root_score_scratch_moves[recycle_i]\n            previous_root_scores[recycle_i] = root_score_scratch_scores[recycle_i]\n        previous_root_valid = 1\n"""
    rep(
        """        if aborted:\n            break\n        best_move = move""",
        """        if aborted:\n            break\n""" + copy + """        best_move = move""",
    )
    rep(
        """        if aborted:\n            break\n        iteration_nodes = int(nodes[0]) - iteration_start""",
        """        if aborted:\n            break\n""" + copy + """        iteration_nodes = int(nodes[0]) - iteration_start""",
    )
    rep(
        """        if aborted:\n            break\n        now_ticks = int(_CPU_CLOCK())""",
        """        if aborted:\n            break\n""" + copy + """        now_ticks = int(_CPU_CLOCK())""",
    )
    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
