#!/usr/bin/env python3
"""Preserve V14's exact H64 emergency fallback while using an early-exit reply-existence probe.

Only iterative_search_stateful_timed_cached is changed. The old fallback materialised every legal
reply after every root move but only consumed whether that count was zero. The replacement asks the
core's exact early-exit legal probe and leaves the H64 score, repetition, mate and stalemate logic
unchanged.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()
start=s.index('def iterative_search_stateful_timed_cached(')
end=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful_timed(',start)
head,block,tail=s[:start],s[start:end],s[end:]
old='''            child_count = _legal_moves_for_state(
                board, -side, child_castling, child_ep, pseudo_stack[1], move_stack[1], eval_stack[1]
            )
            if child_count == 0:
                fallback_score = MATE - 1 if _state_in_check(board, -side, eval_stack[1]) else 0
            else:
                fallback_score = -_evaluate_state(-side, eval_stack[1])
'''
new='''            child_king = int(
                eval_stack[1][EVAL_WHITE_KING]
                if -side == WHITE
                else eval_stack[1][EVAL_BLACK_KING]
            )
            child_has_move = has_any_legal_move_with_king(
                board, -side, child_castling, child_ep, pseudo_stack[1], child_king
            )
            if not child_has_move:
                fallback_score = MATE - 1 if _state_in_check(board, -side, eval_stack[1]) else 0
            else:
                fallback_score = -_evaluate_state(-side, eval_stack[1])
'''
if block.count(old)!=1:raise SystemExit(f'timed fallback anchor count={block.count(old)}')
block=block.replace(old,new,1)
p.write_text(head+block+tail)
