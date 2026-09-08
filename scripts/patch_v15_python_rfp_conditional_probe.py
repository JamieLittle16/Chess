#!/usr/bin/env python3
"""Skip full legal generation only when shallow RFP would actually cut.

V1 probed for any legal move at every RFP-eligible node and paid a small global NPS tax. V2 first
computes the same cheap static evaluation. Only a node whose static score clears the RFP margin pays
the early-exit legality probe; successful cutoffs then avoid complete legal-move materialisation.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
old='''    alpha_original = alpha
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
new='''    alpha_original = alpha
    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    checked = _state_in_check(board, side, eval_stack[ply])

    # Conditional early-probe RFP. Static evaluation is nonterminal-safe because it is never
    # returned until an early legal-move probe has proved this node has a move. Nodes that do not
    # clear the RFP threshold pay no extra probe and fall through to the exact old legal-list path.
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
            if not has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                # RFP is restricted to non-check nodes, so no legal move means stalemate.
                return 0, False
            return pruning_static_eval, False

    count = _legal_moves_for_state(
        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
    )
    if count == 0:
        return (-MATE + ply if checked else 0), False
'''
if s.count(old)!=1: raise SystemExit(f'RFP block count={s.count(old)}')
p.write_text(s.replace(old,new,1))
