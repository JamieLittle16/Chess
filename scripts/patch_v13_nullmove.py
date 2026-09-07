#!/usr/bin/env python3
"""Patch exact V13 with conservative null-move pruning for equal-node screening."""
from __future__ import annotations
import argparse
from pathlib import Path


def once(s:str,old:str,new:str,label:str)->str:
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label} anchor count={n}')
    return s.replace(old,new,1)


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('path',type=Path)
    ap.add_argument('--reduction',type=int,required=True); ap.add_argument('--min-phase',type=int,required=True)
    args=ap.parse_args()
    if args.reduction<2 or args.reduction>4: raise SystemExit('reduction out of conservative range')
    p=args.path; source=p.read_text()
    start=source.find('def _negamax('); end=source.find('\n@njit',start+1)
    if start<0 or end<0: raise SystemExit('negamax bounds missing')
    n=source[start:end]
    anchor='''    checked = _state_in_check(board, side, eval_stack[ply])
    # Conservative reverse-futility pruning ported from the accepted Rust policy. Rule draws and
'''
    insert=f'''    checked = _state_in_check(board, side, eval_stack[ply])

    # Conservative null-move pruning. The -2 EP sentinel marks the immediate null child so two
    # consecutive synthetic passes are impossible. Sparse endgames are excluded by phase and own
    # non-pawn-material gates; only zero-window nodes with a classical static fail-high may probe.
    if (
        depth >= 5
        and beta == alpha + 1
        and not checked
        and ep_square != -2
        and halfmove_clock < 80
        and abs(beta) < MATE_THRESHOLD
        and int(eval_stack[ply, EVAL_PHASE]) >= {args.min_phase}
        and _has_nonpawn_material(board, side)
        and _evaluate_state_classical(side, eval_stack[ply]) >= beta
    ):
        for eval_index in range(EVAL_WIDTH):
            eval_stack[ply + 1, eval_index] = eval_stack[ply, eval_index]
        path_keys[ply + 1] = position_key(board, -side, castling, -1)
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, halfmove_clock
        )
        null_depth = depth - 1 - {args.reduction}
        null_child_score, null_aborted = _negamax(
            board,
            -side,
            castling,
            -2,
            halfmove_clock,
            null_depth,
            -beta,
            -beta + 1,
            ply + 1,
            nodes,
            max_nodes,
            hard_deadline_ticks,
            pseudo_stack,
            move_stack,
            score_stack,
            eval_stack,
            history_keys,
            history_count,
            path_keys,
            killers,
            hash_keys,
            hash_moves,
            history_contexts,
            tt_table,
        )
        if null_aborted:
            return 0, True
        if -null_child_score >= beta:
            return beta, False

    # Conservative reverse-futility pruning ported from the accepted Rust policy. Rule draws and
'''
    n=once(n,anchor,insert,'null insertion')
    source=source[:start]+n+source[end:]
    p.write_text(source)
    return 0

if __name__=='__main__': raise SystemExit(main())
