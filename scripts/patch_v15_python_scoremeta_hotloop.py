#!/usr/bin/env python3
"""Reuse move-order inspection to eliminate repeated hot-loop move classification.

Requires the one-pass presort patch to have been applied first. The score buffer stores

    packed = exact_order_score * 4 + tactical_bit*2 + pawn_bit

Sorting compares only packed>>2, so the exact stable move order is unchanged. Normal negamax,
qsearch and root then recover tactical/pawn metadata from the low bits instead of re-reading board
squares and decoding promotion/EP for _is_tactical and _next_halfmove_clock.
"""
from pathlib import Path
import sys

p=Path(sys.argv[1]);s=p.read_text()

anchor='''@njit(cache=False)\ndef _move_order_score(board: np.ndarray, move: int, preferred: int) -> int:\n'''
pos=s.find(anchor)
if pos<0: raise SystemExit('move-order scorer anchor missing')
end=s.find('\n\n@njit(cache=False)\ndef _order_moves(',pos)
if end<0: raise SystemExit('order_moves anchor missing')
meta_score='''@njit(cache=False, inline="always")\ndef _move_order_score_meta(board: np.ndarray, move: int, preferred: int) -> int:\n    from_square = move_from(move)\n    to_square = move_to(move)\n    promotion = move_promotion(move)\n    signed_attacker = int(board[from_square])\n    attacker = abs(signed_attacker)\n    target = abs(int(board[to_square]))\n    ep = bool(move & FLAG_EP)\n    if ep:\n        target = PAWN\n\n    if move == preferred:\n        score = 10_000_000\n    else:\n        score = 0\n        if target:\n            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])\n        if promotion:\n            score += 6_000_000 + int(PIECE_VALUE[promotion])\n        if attacker == PAWN and target == 0 and not ep and promotion == 0:\n            raw_rank = to_square >> 3\n            relative_rank = raw_rank if signed_attacker > 0 else 7 - raw_rank\n            if relative_rank == 6:\n                score += 5_200_000\n        score += int(ORDER_CENTER_BONUS[to_square])\n\n    tactical = ep or target != 0 or promotion != 0\n    return score * 4 + (2 if tactical else 0) + (1 if attacker == PAWN else 0)\n\n\n'''
s=s[:end]+'\n\n'+meta_score+s[end+2:]

old='''    """Score legal moves once, then materialise the stable descending order once."""\n    for index in range(count):\n        scores[index] = _move_order_score(board, int(moves[index]), preferred)\n    for index in range(1, count):\n        move = int(moves[index])\n        score = int(scores[index])\n        cursor = index - 1\n        while cursor >= 0 and int(scores[cursor]) < score:\n            moves[cursor + 1] = moves[cursor]\n            scores[cursor + 1] = scores[cursor]\n            cursor -= 1\n        moves[cursor + 1] = move\n        scores[cursor + 1] = score\n'''
new='''    """Score legal moves once, carrying tactical/pawn metadata in two low bits."""\n    for index in range(count):\n        scores[index] = _move_order_score_meta(board, int(moves[index]), preferred)\n    for index in range(1, count):\n        move = int(moves[index])\n        packed = int(scores[index])\n        score = packed >> 2\n        cursor = index - 1\n        while cursor >= 0 and (int(scores[cursor]) >> 2) < score:\n            moves[cursor + 1] = moves[cursor]\n            scores[cursor + 1] = scores[cursor]\n            cursor -= 1\n        moves[cursor + 1] = move\n        scores[cursor + 1] = packed\n'''
if s.count(old)!=1: raise SystemExit(f'presorted order_moves anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''    """Order PV/tacticals, killers and quiets once; search then consumes linearly."""\n    for index in range(count):\n        move = int(moves[index])\n        score = _move_order_score(board, move, preferred)\n        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n        scores[index] = score\n    for index in range(1, count):\n        move = int(moves[index])\n        score = int(scores[index])\n        cursor = index - 1\n        while cursor >= 0 and int(scores[cursor]) < score:\n            moves[cursor + 1] = moves[cursor]\n            scores[cursor + 1] = scores[cursor]\n            cursor -= 1\n        moves[cursor + 1] = move\n        scores[cursor + 1] = score\n'''
new='''    """Order once while carrying tactical/pawn metadata in two low score bits."""\n    for index in range(count):\n        move = int(moves[index])\n        packed = _move_order_score_meta(board, move, preferred)\n        score = packed >> 2\n        meta = packed & 3\n        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n        scores[index] = score * 4 + meta\n    for index in range(1, count):\n        move = int(moves[index])\n        packed = int(scores[index])\n        score = packed >> 2\n        cursor = index - 1\n        while cursor >= 0 and (int(scores[cursor]) >> 2) < score:\n            moves[cursor + 1] = moves[cursor]\n            scores[cursor + 1] = scores[cursor]\n            cursor -= 1\n        moves[cursor + 1] = move\n        scores[cursor + 1] = packed\n'''
if s.count(old)!=1: raise SystemExit(f'presorted killer anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''        move = int(moves[index])\n        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n        # Only the exact V13 prefix is live below qply 0.'''
new='''        move = int(moves[index])\n        packed_order = int(score_stack[ply, index])\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        # Only the exact V13 prefix is live below qply 0.'''
if s.count(old)!=1: raise SystemExit(f'qsearch halfmove anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''        move = int(moves[index])\n        order_score = int(score_stack[ply, index])\n        # Submission-V11 recursive semantics: immediate-promotion verification is root-only.\n        # Recursive quiet pawn pushes are ordinary quiets, so do not pay for a promotion classifier\n        # in this hot loop or bias LMR/futility/killer behaviour here.\n        quiet = not _is_tactical(board, move)\n        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n'''
new='''        move = int(moves[index])\n        packed_order = int(score_stack[ply, index])\n        order_score = packed_order >> 2\n        # The ordering pass already classified this move while its board squares were hot.\n        quiet = (packed_order & 2) == 0\n        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n'''
if s.count(old)!=1: raise SystemExit(f'negamax metadata anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''        move = int(moves[index])\n        child_depth = depth - 1\n        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:\n'''
new='''        move = int(moves[index])\n        packed_order = int(score_stack[0, index])\n        child_depth = depth - 1\n        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:\n'''
if s.count(old)!=1: raise SystemExit(f'root move anchor count={s.count(old)}')
s=s.replace(old,new,1)
old='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n'''
new='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n'''
root_start=s.index('def _root(');root_end=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(',root_start)
root_block=s[root_start:root_end]
if root_block.count(old)!=1: raise SystemExit(f'root halfmove anchor count={root_block.count(old)}')
root_block=root_block.replace(old,new,1)
s=s[:root_start]+root_block+s[root_end:]

p.write_text(s)
