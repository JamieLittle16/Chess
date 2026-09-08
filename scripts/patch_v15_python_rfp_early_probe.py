#!/usr/bin/env python3
"""Move V14 reverse-futility cutoff ahead of full legal-move materialisation.

The accepted Rust search proves a shallow non-check scout node nonterminal with an early-exit
legal-move probe before paying for the complete legal list. Python V14 currently materialises every
legal move first and only then performs the same RFP cutoff. This patch preserves the cutoff score
and all terminal semantics while avoiding full move generation on successful RFP nodes.
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

    # Search-v2 RFP early-exit shape: on the same shallow non-check scout nodes, first prove that
    # at least one legal move exists with the core's early-exit probe. A successful RFP cutoff then
    # avoids constructing and filtering the complete legal list. Because this branch is explicitly
    # non-check, "no legal move" is stalemate and returns zero exactly as the old full-list path did.
    pruning_static_eval = INFINITY
    pruning_eligible = (
        depth <= 3
        and beta == alpha + 1
        and not checked
        and abs(beta) < MATE_THRESHOLD
        and _has_nonpawn_material(board, side)
    )
    if pruning_eligible:
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
