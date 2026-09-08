#!/usr/bin/env python3
"""Move V14 reverse-futility cutoff ahead of full legal-move materialisation.

V2 computes the cheap classical RFP bound first and only calls the early-exit legal-move probe when
the node is actually about to cut. This preserves all terminal semantics while avoiding both full
move generation on successful RFP nodes and unnecessary legal probes on non-cutting scout nodes.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    count = _legal_moves_for_state(
        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
    )
    if count == 0:
        return (-MATE + ply if _state_in_check(board, side, eval_stack[ply]) else 0), False

    checked = _state_in_check(board, side, eval_stack[ply])
    # Conservative reverse-futility pruning ported from the accepted Rust policy. Rule draws and
    # terminal positions were handled first; only shallow non-check scout nodes with own non-pawn
    # material may return the static lower bound.
    pruning_static_eval = INFINITY
    if (
        depth <= 3
        and beta == alpha + 1
        and not checked
        and abs(beta) < MATE_THRESHOLD
        and _has_nonpawn_material(board, side)
    ):
        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])
        if pruning_static_eval - 120 * depth >= beta:
            return pruning_static_eval, False
'''
new = '''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    checked = _state_in_check(board, side, eval_stack[ply])

    # Compute the RFP bound before materialising the complete legal list. Only when the bound would
    # actually cut do we pay for the core's early-exit legality probe, which distinguishes a real
    # nonterminal cutoff from stalemate. Non-cutting nodes fall through to the exact old full-list
    # path with no extra legal probe.
    pruning_static_eval = INFINITY
    pruning_eligible = (
        depth <= 3
        and beta == alpha + 1
        and not checked
        and abs(beta) < MATE_THRESHOLD
        and _has_nonpawn_material(board, side)
    )
    if pruning_eligible:
        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])
        if pruning_static_eval - 120 * depth >= beta:
            own_king = int(
                eval_stack[ply][EVAL_WHITE_KING]
                if side == WHITE
                else eval_stack[ply][EVAL_BLACK_KING]
            )
            if has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                return pruning_static_eval, False
            return 0, False

    count = _legal_moves_for_state(
        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
    )
    if count == 0:
        return (-MATE + ply if checked else 0), False
'''
if s.count(old) != 1:
    raise SystemExit(f"RFP block: expected 1 occurrence, found {s.count(old)}")
s = s.replace(old, new, 1)
p.write_text(s)
