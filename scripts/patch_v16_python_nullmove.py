#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
mode = sys.argv[2] if len(sys.argv) > 2 else "r2"
if mode not in {"r2", "r3", "verified"}:
    raise SystemExit(mode)


def one(old: str, new: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor {n}: {old[:80]!r}")
    s = s.replace(old, new, 1)


one(
    "TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\n",
    "TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\nNULL_DISABLE_CASTLING_FLAG = 16\nNULL_MIN_DEPTH = 5\n",
)

one(
    '''    return key\n\n\n@njit(cache=False, inline="always")\ndef _history_context_mix''',
    '''    return key\n\n\n@njit(cache=False, inline="always")\ndef _null_position_key(\n    current_key: np.uint64, board: np.ndarray, side: int, ep_square: int\n) -> np.uint64:\n    # Search-only null move: flip side-to-move and clear a legal en-passant key.\n    key = current_key ^ REPETITION_SIDE_KEY\n    if ep_square >= 0 and _has_legal_en_passant(board, side, ep_square):\n        key ^= REPETITION_EP_KEYS[ep_square]\n    return key\n\n\n@njit(cache=False, inline="always")\ndef _history_context_mix''',
)

insert_anchor = '''        if pruning_static_eval - 120 * depth >= beta:\n            return pruning_static_eval, False\n\n    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))\n'''

if mode == "r2":
    reduction = "2"
    verify = '''            if null_score >= beta:\n                return null_score, False\n'''
elif mode == "r3":
    reduction = "2 + (1 if depth >= 8 else 0)"
    verify = '''            if null_score >= beta:\n                return null_score, False\n'''
else:
    reduction = "2 + (1 if depth >= 8 else 0)"
    verify = '''            if null_score >= beta:\n                # Reduced-depth verification at the real position with null disabled.\n                verify_depth = max(0, depth - 1 - null_reduction)\n                verify_score, verify_aborted = _negamax(\n                    board, side, castling | NULL_DISABLE_CASTLING_FLAG, ep_square,\n                    halfmove_clock, verify_depth, beta - 1, beta, ply,\n                    nodes, max_nodes, hard_deadline_ticks,\n                    pseudo_stack, move_stack, score_stack, eval_stack,\n                    history_keys, history_count, path_keys, killers, lmr_history,\n                    hash_keys, hash_moves, history_contexts, student_edges, tt_table,\n                )\n                if verify_aborted:\n                    return 0, True\n                if verify_score >= beta:\n                    return verify_score, False\n'''

block = f'''        if pruning_static_eval - 120 * depth >= beta:\n            return pruning_static_eval, False\n\n    # Conservative search-only null-move pruning. Null is disabled throughout the null subtree\n    # using an otherwise-unused castling high bit; legal castling rights occupy only the low 4 bits.\n    # Resetting the fictional null subtree's halfmove clock suppresses repetition/50-move artefacts.\n    if (\n        depth >= NULL_MIN_DEPTH\n        and scout_node\n        and not checked\n        and (castling & NULL_DISABLE_CASTLING_FLAG) == 0\n        and abs(beta) < MATE_THRESHOLD\n        and _has_nonpawn_material(board, side)\n    ):\n        null_static_eval = _evaluate_state_classical(side, eval_stack[ply])\n        if null_static_eval >= beta:\n            _materialize_student_path(eval_stack, student_edges, ply)\n            for null_i in range(EVAL_WIDTH):\n                eval_stack[ply + 1, null_i] = eval_stack[ply, null_i]\n            student_edges[ply + 1] = np.uint64(0)\n            path_keys[ply + 1] = _null_position_key(current_key, board, side, ep_square)\n            history_contexts[ply + 1] = current_context\n            null_reduction = {reduction}\n            null_depth = max(0, depth - 1 - null_reduction)\n            null_child, null_aborted = _negamax(\n                board, -side, castling | NULL_DISABLE_CASTLING_FLAG, -1, 0, null_depth,\n                -beta, -beta + 1, ply + 1, nodes, max_nodes, hard_deadline_ticks,\n                pseudo_stack, move_stack, score_stack, eval_stack,\n                history_keys, history_count, path_keys, killers, lmr_history,\n                hash_keys, hash_moves, history_contexts, student_edges, tt_table,\n            )\n            if null_aborted:\n                return 0, True\n            null_score = -null_child\n{verify}\n    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))\n'''

one(insert_anchor, block)
p.write_text(s)
print("patched null move", mode)
