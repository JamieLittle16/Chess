#!/usr/bin/env python3
"""Move Python RFP ahead of full legal-list construction, matching accepted Rust search.

Semantics are unchanged: on an eligible non-check scout node we first prove that at least one legal
move exists with the existing exact early-exit helper. If RFP cuts, the full legal list is never
materialised. If it does not cut, ordinary legal generation proceeds exactly as before.
"""
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit('usage: patch_v15_python_rfp_early_legal.py SEARCH.py')
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
    checked = _state_in_check(board, side, eval_stack[ply])
    # Rust-faithful RFP ordering: on an eligible scout node, prove nonterminality with the exact
    # early-exit legal-existence helper before paying to construct the complete legal move list.
    pruning_static_eval = INFINITY
    if (
        depth <= 3
        and beta == alpha + 1
        and not checked
        and abs(beta) < MATE_THRESHOLD
        and _has_nonpawn_material(board, side)
    ):
        pseudo = pseudo_stack[ply]
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        if not has_any_legal_move_with_king(
            board, side, castling, ep_square, pseudo, own_king
        ):
            return 0, False
        pruning_static_eval = _evaluate_state_classical(side, eval_stack[ply])
        if pruning_static_eval - 120 * depth >= beta:
            return pruning_static_eval, False

    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    count = _legal_moves_for_state(
        board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
    )
    if count == 0:
        return (-MATE + ply if checked else 0), False

'''
if s.count(old)!=1:
    raise SystemExit(f'RFP/legal-list anchor count={s.count(old)}')
s=s.replace(old,new,1)
p.write_text(s)
