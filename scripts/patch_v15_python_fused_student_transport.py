#!/usr/bin/env python3
"""Fuse V14 H64 accumulator transport, optionally deferring it past late-quiet futility.

Modes:
  fused     Replace copy + 2..5 separate 64-lane delta loops by one direct 64-lane loop.
  deferred  Also split the exact V13 prefix from H64 transport in recursive normal search and
            materialise the fused H64 child only after the existing futility gate.

Both modes are intended to be bit-identical at fixed nodes.
"""
from __future__ import annotations

from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_fused_student_transport.py SEARCH.py fused|deferred")
p=Path(sys.argv[1]); mode=sys.argv[2]
if mode not in ("fused","deferred"): raise SystemExit("mode must be fused or deferred")
s=p.read_text()

# Snapshot the exact prefix transport before changing the full transport.  This is used only by the
# deferred recursive path; qsearch/root/fallback continue to call the full exact state transport.
fn_start=s.index('@njit(cache=False)\ndef _advance_eval_state_into(')
fn_end=s.index('\n@njit(cache=False, inline="always")\ndef _repetition_piece_index',fn_start)
full_fn=s[fn_start:fn_end]
old_tail='''    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )
'''
if full_fn.count(old_tail)!=1: raise SystemExit('full transport tail anchor mismatch')
prefix_fn=full_fn.replace('def _advance_eval_state_into(', 'def _advance_eval_prefix_into(',1).replace(old_tail,'',1)

helpers='''
@njit(cache=False, inline="always")
def _student_feature_encoded(signed_piece: int, square: int, add: int) -> int:
    color_base = 0 if signed_piece > 0 else 384
    feature = color_base + (abs(signed_piece) - 1) * 64 + square
    return feature + 1 if add > 0 else -(feature + 1)


@njit(cache=False, inline="always")
def _prepare_student_delta4(board: np.ndarray, side: int, move: int) -> tuple[int, int, int, int]:
    from_square=move_from(move); to_square=move_to(move); promotion=move_promotion(move)
    moving_signed=int(board[from_square]); placed_signed=side*promotion if promotion else moving_signed
    d0=_student_feature_encoded(moving_signed,from_square,-1)
    d1=_student_feature_encoded(placed_signed,to_square,1)
    d2=0; d3=0
    captured_square=to_square; captured_signed=int(board[to_square])
    if move & FLAG_EP:
        captured_square=to_square-8*side; captured_signed=int(board[captured_square])
    if captured_signed!=EMPTY:
        d1=_student_feature_encoded(captured_signed,captured_square,-1)
        d2=_student_feature_encoded(placed_signed,to_square,1)
    if move & FLAG_CASTLE:
        if to_square==6: rook_from,rook_to=7,5
        elif to_square==2: rook_from,rook_to=0,3
        elif to_square==62: rook_from,rook_to=63,61
        else: rook_from,rook_to=56,59
        rook_signed=side*ROOK
        d2=_student_feature_encoded(rook_signed,rook_from,-1)
        d3=_student_feature_encoded(rook_signed,rook_to,1)
    return d0,d1,d2,d3


@njit(cache=False, inline="always")
def _student_delta_weight(encoded: int, lane: int) -> int:
    if encoded > 0:
        return int(STUDENT_FEATURE_WEIGHTS[encoded-1,lane])
    if encoded < 0:
        return -int(STUDENT_FEATURE_WEIGHTS[-encoded-1,lane])
    return 0


@njit(cache=False, inline="always")
def _advance_student_delta4_fused(
    parent: np.ndarray, child: np.ndarray, d0: int, d1: int, d2: int, d3: int
) -> None:
    for lane in range(STUDENT_HIDDEN):
        value=int(parent[STUDENT_OFFSET+lane])
        value += _student_delta_weight(d0,lane)
        value += _student_delta_weight(d1,lane)
        value += _student_delta_weight(d2,lane)
        value += _student_delta_weight(d3,lane)
        child[STUDENT_OFFSET+lane]=value


'''
# Place helpers before the state transport.  In deferred mode also expose the prefix clone.
insert = helpers + (prefix_fn + '\n\n' if mode=='deferred' else '')
s=s[:fn_start]+insert+s[fn_start:]

# Replace the full transport's old H64 call with one fused row-wise pass. This benefits qsearch/root
# and, in fused mode, normal recursive search too.
old_tail_count=s.count(old_tail)
if old_tail_count!=1: raise SystemExit(f'global full transport tail count={old_tail_count}')
new_tail='''    sd0,sd1,sd2,sd3=_prepare_student_delta4(board,side,move)
    _advance_student_delta4_fused(parent,child,sd0,sd1,sd2,sd3)
'''
s=s.replace(old_tail,new_tail,1)

if mode=='deferred':
    old='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )

        # Adaptive verified LMR v3. Captures/promotions, both killers, checks, nodes in check and
'''
    new='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        sd0,sd1,sd2,sd3=_prepare_student_delta4(board,side,move)
        _advance_eval_prefix_into(board,side,move,eval_stack[ply],eval_stack[ply+1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )

        # Adaptive verified LMR v3. Captures/promotions, both killers, checks, nodes in check and
'''
    if s.count(old)!=1: raise SystemExit(f'deferred pre-prune anchor count={s.count(old)}')
    s=s.replace(old,new,1)
    old2='''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        if gives_check:
            reduction = 0
'''
    new2='''        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue

        # Only surviving recursive children pay the H64 transport and TT/repetition identity cost.
        _advance_student_delta4_fused(eval_stack[ply],eval_stack[ply+1],sd0,sd1,sd2,sd3)
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(current_context,current_key,child_halfmove)

        if gives_check:
            reduction = 0
'''
    if s.count(old2)!=1: raise SystemExit(f'deferred post-prune anchor count={s.count(old2)}')
    s=s.replace(old2,new2,1)

p.write_text(s)
