#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: apply_v18_verified_null.py <numba_search.py>")
    p = Path(sys.argv[1])
    s = p.read_text()
    old = '''            if null_score >= beta:\n                return null_score, False\n'''
    new = '''            if null_score >= beta:\n                verify_depth = max(0, depth - 2)\n                verify_score, verify_aborted = _negamax(\n                    board, side, castling | NULL_DISABLE_CASTLING_FLAG, ep_square, halfmove_clock, verify_depth,\n                    beta - 1, beta, ply, nodes, max_nodes, hard_deadline_ticks,\n                    pseudo_stack, move_stack, score_stack, eval_stack,\n                    history_keys, history_count, path_keys, killers, quiet_history, move_context_stack,\n                    hash_keys, hash_moves, history_contexts, student_edges, tt_table,\n                )\n                if verify_aborted:\n                    return 0, True\n                if verify_score >= beta:\n                    return verify_score, False\n'''
    if s.count(old) != 1:
        raise SystemExit(f"expected one null cutoff site, found {s.count(old)}")
    p.write_text(s.replace(old, new, 1))
    print("APPLIED_VERIFIED_NULL")


if __name__ == "__main__":
    main()
