#!/usr/bin/env python3
"""Apply a conservative root-aspiration experiment to extracted PUNCH133."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    ap.add_argument("--width", type=int, default=50)
    args = ap.parse_args()
    if args.width <= 0:
        raise ValueError("--width must be positive")

    p = args.path
    s = p.read_text()

    def rep(old: str, new: str, count: int = 1) -> None:
        nonlocal s
        actual = s.count(old)
        if actual != count:
            raise RuntimeError(f"patch anchor count {actual} != {count}: {old[:120]!r}")
        s = s.replace(old, new, count)

    rep(
        """    depth: int,\n    preferred: int,\n    nodes: np.ndarray,""",
        """    depth: int,\n    preferred: int,\n    root_alpha: int,\n    root_beta: int,\n    nodes: np.ndarray,""",
    )
    rep(
        """    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = -INFINITY\n""",
        """    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = root_alpha\n    beta = root_beta\n""",
    )
    rep(
        """                board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                -INFINITY, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,""",
        """                board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                -beta, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,""",
    )
    rep(
        """                    board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                    -INFINITY, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,""",
        """                    board, -side, child_castling, child_ep, child_halfmove, child_depth,\n                    -beta, -alpha, np.int64(1), nodes, max_nodes, hard_deadline_ticks,""",
    )
    rep(
        """        if score > alpha:\n            alpha = score\n    return best_move, best_score, False\n""",
        """        if score > alpha:\n            alpha = score\n        if alpha >= beta:\n            break\n    return best_move, best_score, False\n""",
    )

    # Non-production callers keep the old full-window semantics exactly.
    rep(
        """            depth,\n            np.int64(best_move),\n            nodes,""",
        """            depth,\n            np.int64(best_move),\n            np.int64(-INFINITY),\n            np.int64(INFINITY),\n            nodes,""",
    )
    rep(
        """            board, side, castling, ep_square, halfmove_clock, depth, np.int64(best_move), nodes, hard_nodes,\n            0,""",
        """            board, side, castling, ep_square, halfmove_clock, depth, np.int64(best_move),\n            np.int64(-INFINITY), np.int64(INFINITY), nodes, hard_nodes,\n            0,""",
    )

    old = """    for depth in range(1, MAX_DEPTH + 1):\n        iter_start_ticks = int(_CPU_CLOCK())\n        move, score, aborted = _root(\n            board, side, castling, ep_square, halfmove_clock, depth, np.int64(root_preferred), nodes, max_nodes,\n            hard_deadline,\n            pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count, path_keys,\n            killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n        )\n        if aborted:\n            break\n        now_ticks = int(_CPU_CLOCK())\n        iteration_ticks = max(1, now_ticks - iter_start_ticks)\n"""
    width = args.width
    new = f"""    for depth in range(1, MAX_DEPTH + 1):\n        iter_start_ticks = int(_CPU_CLOCK())\n        # Conservative root aspiration. From depth 5 onward the last completed root score is\n        # the strongest available centre for this exact position. A narrow window makes the\n        # PVS first move cheaper; fail-low/high widens geometrically and retries using TT work\n        # just produced. An interrupted retry never replaces the last completed depth.\n        aspiration_delta = np.int64({width})\n        root_alpha = np.int64(-INFINITY)\n        root_beta = np.int64(INFINITY)\n        if depth >= 5 and abs(best_score) < MATE_THRESHOLD:\n            root_alpha = np.int64(max(-INFINITY, best_score - aspiration_delta))\n            root_beta = np.int64(min(INFINITY, best_score + aspiration_delta))\n        aborted = False\n        while True:\n            move, score, aborted = _root(\n                board, side, castling, ep_square, halfmove_clock, depth, np.int64(root_preferred),\n                root_alpha, root_beta, nodes, max_nodes, hard_deadline,\n                pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count, path_keys,\n                killers, quiet_history, move_context_stack, hash_keys, hash_moves, history_contexts, student_edges,\n                tt_table,\n            )\n            if aborted:\n                break\n            if score <= root_alpha and root_alpha > -INFINITY:\n                aspiration_delta = min(np.int64(1600), aspiration_delta * np.int64(2))\n                root_alpha = np.int64(max(-INFINITY, score - aspiration_delta))\n                continue\n            if score >= root_beta and root_beta < INFINITY:\n                aspiration_delta = min(np.int64(1600), aspiration_delta * np.int64(2))\n                root_beta = np.int64(min(INFINITY, score + aspiration_delta))\n                continue\n            break\n        if aborted:\n            break\n        now_ticks = int(_CPU_CLOCK())\n        iteration_ticks = max(1, now_ticks - iter_start_ticks)\n"""
    rep(old, new)

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
