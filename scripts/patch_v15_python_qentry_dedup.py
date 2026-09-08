#!/usr/bin/env python3
"""Skip rule-draw/dead-material predicates duplicated at the negamax->qsearch boundary.

Every qply==0 call is made immediately by _negamax(depth<=0) after _negamax has already checked the
same unchanged position for rule draw and elementary dead material. Keep qsearch's own node-budget
increment exactly where it is, but run those position predicates only for recursive qsearch plies.
This changes no board state, score, move ordering, node counting or abort semantics.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='''    if _is_rule_draw(halfmove_clock, ply, history_keys, history_count, path_keys):\n        # Checkmate ends the game immediately and takes precedence over a claimable draw.\n        if _state_in_check(board, side, eval_stack[ply]):\n            pseudo = pseudo_stack[ply]\n            legal = move_stack[ply]\n            if _legal_moves_for_state(\n                board, side, castling, ep_square, pseudo, legal, eval_stack[ply]\n            ) == 0:\n                return -MATE + ply, False\n        return 0, False\n\n    if _is_elementary_dead_material(board, eval_stack[ply]):\n        return 0, False\n\n    checked = _state_in_check(board, side, eval_stack[ply])\n'''
new='''    # qply==0 is entered directly from _negamax after these exact two predicates have already\n    # been evaluated on the same unchanged position. Recursive qsearch plies still perform them.\n    if qply != 0:\n        if _is_rule_draw(halfmove_clock, ply, history_keys, history_count, path_keys):\n            # Checkmate ends the game immediately and takes precedence over a claimable draw.\n            if _state_in_check(board, side, eval_stack[ply]):\n                pseudo = pseudo_stack[ply]\n                legal = move_stack[ply]\n                if _legal_moves_for_state(\n                    board, side, castling, ep_square, pseudo, legal, eval_stack[ply]\n                ) == 0:\n                    return -MATE + ply, False\n            return 0, False\n\n        if _is_elementary_dead_material(board, eval_stack[ply]):\n            return 0, False\n\n    checked = _state_in_check(board, side, eval_stack[ply])\n'''
if s.count(old)!=1: raise SystemExit(f'qentry predicate anchor count={s.count(old)}')
p.write_text(s.replace(old,new,1))
