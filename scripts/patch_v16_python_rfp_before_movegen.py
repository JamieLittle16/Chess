#!/usr/bin/env python3
"""Move conservative RFP ahead of full legal-move generation without changing semantics.

At eligible non-check scout nodes the old search generated every legal move, then computed the
classical static bound and often returned immediately. The candidate computes that cheap bound
first. If it would cut, an existing early-exit legal-move probe rules out stalemate before returning.
If it would not cut, the original full move generation and all downstream search are unchanged.

The patch is intended to be fixed-node exact: same move, score, depth and node count.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: patch_v16_python_rfp_before_movegen.py SEARCH.py')
p=Path(sys.argv[1]); s=p.read_text()

n0=s.index('@njit(cache=False)\ndef _negamax(')
n1=s.index('\n\n@njit(cache=False)\ndef _root(',n0)
n=s[n0:n1]

start=n.index('    alpha_original = alpha\n')
end=n.index('    hash_index = int(current_key & np.uint64(HASH_MOVE_MASK))\n',start)
old=n[start:end]

# Tolerate the Rust-history patch's node_null_window line while replacing the whole pre-order block.
if 'pseudo = pseudo_stack[ply]' not in old or 'pruning_static_eval = INFINITY' not in old:
    raise SystemExit('unexpected pre-order block')
node_null='    node_null_window = beta == alpha + 1\n' if 'node_null_window = beta == alpha + 1' in old else ''

new='''    alpha_original = alpha
'''+node_null+'''    checked = _state_in_check(board, side, eval_stack[ply])

    # Compute the cheap classical RFP bound before full move generation.  A successful cutoff still
    # has to exclude stalemate, but has_any_legal_move_with_king exits on the first legal move and is
    # substantially cheaper than materialising/sorting the whole list.
    pruning_static_eval = INFINITY
    rfp_would_cut = False
    if (
        depth <= 3
        and beta == alpha + 1
        and not checked
        and abs(beta) < MATE_THRESHOLD
    ):
        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])
        if pruning_static_eval - 120 * depth >= beta and _has_nonpawn_material(board, side):
            rfp_would_cut = True

    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    if rfp_would_cut:
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        if has_any_legal_move_with_king(
            board, side, castling, ep_square, pseudo, own_king
        ):
            return pruning_static_eval, False
        # Non-check + no legal move is stalemate.  Preserve terminal precedence exactly.
        return 0, False

    count = _legal_moves_for_state(
        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
    )
    if count == 0:
        return (-MATE + ply if checked else 0), False

'''
n=n[:start]+new+n[end:]
s=s[:n0]+n+s[n1:]
p.write_text(s)
