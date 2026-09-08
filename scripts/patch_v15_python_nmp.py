#!/usr/bin/env python3
"""Add conservative null-move pruning to exact packaged V14 for qualification.

The null branch is search-only: it flips side-to-move, clears EP, preserves the board/evaluator,
and uses a negative halfmove sentinel so artificial null nodes cannot create repetition/50-move
claims or immediately null again. Terminal/check/low-material positions are excluded before use.
"""
from pathlib import Path
import sys

if len(sys.argv) != 7:
    raise SystemExit("usage: patch_v15_python_nmp.py SEARCH.py MIN_DEPTH MARGIN BASE DIVISOR MIN_PHASE")
p=Path(sys.argv[1]); min_depth,margin,base,divisor,min_phase=map(int,sys.argv[2:]); s=p.read_text()
anchor='''    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))
    hash_preferred = int(hash_moves[hash_index]) if hash_keys[hash_index] == current_key else -1
'''
insert=f'''    # V15 null-move pruning experiment. Only scout nodes with a comfortably high static score,
    # non-pawn material and enough phase may try an artificial pass. ``halfmove_clock < 0`` marks
    # a null child: it suppresses repetition/50-move claims there and prevents consecutive nulls.
    if (
        depth >= {min_depth}
        and beta == alpha + 1
        and not checked
        and halfmove_clock >= 0
        and abs(beta) < MATE_THRESHOLD
        and int(eval_stack[ply][EVAL_PHASE]) >= {min_phase}
        and _has_nonpawn_material(board, side)
    ):
        null_static = _evaluate_state_v13_only(side, eval_stack[ply])
        if null_static >= beta + {margin}:
            for eval_index in range(EVAL_WIDTH):
                eval_stack[ply + 1, eval_index] = eval_stack[ply, eval_index]
            path_keys[ply + 1] = position_key(board, -side, castling, -1)
            history_contexts[ply + 1] = _child_history_context(
                current_context, current_key, 0
            )
            null_reduction = {base} + depth // {divisor}
            null_depth = max(0, depth - 1 - null_reduction)
            null_child, null_aborted = _negamax(
                board, -side, castling, -1, -1, null_depth,
                -beta, -beta + 1, ply + 1, nodes, max_nodes, hard_deadline_ticks,
                pseudo_stack, move_stack, score_stack, eval_stack, history_keys, history_count,
                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,
            )
            if null_aborted:
                return 0, True
            if -null_child >= beta:
                # Return the bound, not a fail-soft null score, so an artificial pass can never
                # manufacture a mate value or pollute callers with an exaggerated exact score.
                return beta, False

    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))
    hash_preferred = int(hash_moves[hash_index]) if hash_keys[hash_index] == current_key else -1
'''
if s.count(anchor)!=1:
    raise SystemExit(f"expected one NMP insertion anchor, found {s.count(anchor)}")
s=s.replace(anchor,insert,1)
p.write_text(s)
