#!/usr/bin/env python3
"""Add conservative qsearch delta pruning to exact packaged V14.

Only non-check, non-promotion, ordinary captures are candidates. The move is made and the child
check state is tested before pruning, so checking captures are always searched. En-passant is kept.
The supplied margin is added to captured material before comparing against the current alpha.
"""
from pathlib import Path
import sys

if len(sys.argv)!=3: raise SystemExit('usage: patch_v15_python_qsearch_delta.py SEARCH.py MARGIN')
p=Path(sys.argv[1]);margin=int(sys.argv[2]);s=p.read_text()
head_old='''    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
'''
head_new='''    checked = _state_in_check(board, side, eval_stack[ply])
    stand_pat = -INFINITY
    if not checked:
'''
if s.count(head_old)!=1:raise SystemExit(f'stand-pat anchor count={s.count(head_old)}')
s=s.replace(head_old,head_new,1)
old='''    for index in range(count):
        _pick_next_scored_move(moves, score_stack[ply], index, count)
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
        # qualified incremental updater performs no work in its appended student-accumulator tail.
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
'''
new=f'''    for index in range(count):
        _pick_next_scored_move(moves, score_stack[ply], index, count)
        move = int(moves[index])
        to_square = move_to(move)
        captured_value = int(PIECE_VALUE[abs(int(board[to_square]))])
        delta_candidate = (
            not checked
            and (move & FLAG_EP) == 0
            and move_promotion(move) == 0
            and captured_value > 0
            and stand_pat + captured_value + {margin} <= alpha
        )
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        if delta_candidate and not _state_in_check(board, -side, eval_stack[ply + 1]):
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue
        path_keys[ply + 1] = _child_position_key(
'''
if s.count(old)!=1:raise SystemExit(f'qsearch loop anchor count={s.count(old)}')
s=s.replace(old,new,1)
p.write_text(s)
