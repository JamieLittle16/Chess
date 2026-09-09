#!/usr/bin/env python3
"""Extend lazy H64 materialisation to root edges.

Apply after the V16 Rust-history and lazy-student patches. The root still updates the exact V13
prefix eagerly, but its H64 tail is represented by the same pending edge used in recursive search.
The first descendant that actually evaluates H64 materialises from the fully-built root state.
Intended semantics: bit-for-bit fixed-node identity with plain lazy-H64.
"""
from pathlib import Path
import sys

if len(sys.argv)!=2:
    raise SystemExit('usage: patch_v16_python_lazy_root.py SEARCH.py')
p=Path(sys.argv[1]);s=p.read_text()
r0=s.index('@njit(cache=False)\ndef _root(')
r1=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(',r0)
r=s[r0:r1]

old='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
'''
new='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        moving_signed = int(board[move_from(move)])
        _advance_eval_state_into(
            board, side, move,
            eval_stack[0, :EVAL_V13_WIDTH],
            eval_stack[1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        student_edges[1] = _pack_student_edge(move, moving_signed, captured_piece)
'''
if r.count(old)!=1:
    raise SystemExit(f'root lazy anchor count={r.count(old)}')
r=r.replace(old,new,1)
s=s[:r0]+r+s[r1:]
p.write_text(s)
