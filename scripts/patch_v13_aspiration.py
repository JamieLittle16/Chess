#!/usr/bin/env python3
"""Patch exact V13 fixed-node iterative search with fail-open root aspiration windows."""
from __future__ import annotations
import argparse
from pathlib import Path


def once(s:str,old:str,new:str,label:str)->str:
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label} anchor count={n}')
    return s.replace(old,new,1)


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument('path',type=Path); ap.add_argument('--width',type=int,required=True)
    args=ap.parse_args()
    if args.width<=0: raise SystemExit('width must be positive')
    p=args.path; source=p.read_text()

    # Patch only the root function. Existing production callers retain full-window defaults; the
    # fixed-node iterative entry below opts into aspiration explicitly for A/B measurement.
    rstart=source.find('def _root(')
    rend=source.find('\n@njit',rstart+1)
    if rstart<0 or rend<0: raise SystemExit('root bounds missing')
    r=source[rstart:rend]
    r=once(r,
        '    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:\n',
        '    tt_table: np.ndarray,\n    alpha_start: int = -INFINITY,\n    beta_start: int = INFINITY,\n) -> tuple[int, int, bool]:\n',
        'root signature')
    r=once(r,'    alpha = -INFINITY\n','    alpha = alpha_start\n    beta = beta_start\n','root alpha')
    # First-PV and later full-window re-searches should respect the aspiration beta.
    if r.count('-INFINITY, -alpha, 1, nodes') != 2:
        raise SystemExit(f'root full-window child anchor count={r.count("-INFINITY, -alpha, 1, nodes")}')
    r=r.replace('-INFINITY, -alpha, 1, nodes','-beta, -alpha, 1, nodes')
    alpha_update='''        if score > alpha:
            alpha = score
    return best_move, best_score, False
'''
    alpha_new='''        if score > alpha:
            alpha = score
        if alpha >= beta:
            break
    return best_move, best_score, False
'''
    r=once(r,alpha_update,alpha_new,'root cutoff')
    source=source[:rstart]+r+source[rend:]

    # Opt only iterative_search_stateful into aspiration for this screening patch. All timed
    # production entries remain syntactically valid and full-window via the defaults above.
    istart=source.find('def iterative_search_stateful(')
    iend=source.find('\n@njit',istart+1)
    if istart<0 or iend<0: raise SystemExit('iterative bounds missing')
    it=source[istart:iend]
    call='''        move, score, aborted = _root(
            board,
            side,
            castling,
            ep_square,
            halfmove_clock,
            depth,
            best_move,
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
'''
    repl=f'''        alpha_start = -INFINITY
        beta_start = INFINITY
        if completed_depth > 0 and depth >= 4 and abs(best_score) < MATE_THRESHOLD:
            alpha_start = max(-INFINITY, best_score - {args.width})
            beta_start = min(INFINITY, best_score + {args.width})
        move, score, aborted = _root(
            board,
            side,
            castling,
            ep_square,
            halfmove_clock,
            depth,
            best_move,
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
            alpha_start,
            beta_start,
        )
        if (
            not aborted
            and (score <= alpha_start or score >= beta_start)
            and (alpha_start != -INFINITY or beta_start != INFINITY)
        ):
            move, score, aborted = _root(
                board,
                side,
                castling,
                ep_square,
                halfmove_clock,
                depth,
                move if move >= 0 else best_move,
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
                -INFINITY,
                INFINITY,
            )
'''
    it=once(it,call,repl,'iterative root call')
    source=source[:istart]+it+source[iend:]
    p.write_text(source)
    return 0

if __name__=='__main__': raise SystemExit(main())
