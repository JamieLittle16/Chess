#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
old = '''    else:\n        own_king = int(\n            eval_stack[ply][EVAL_WHITE_KING]\n            if side == WHITE\n            else eval_stack[ply][EVAL_BLACK_KING]\n        )\n        count = generate_legal_tactical_moves_into_with_king(\n            board, side, ep_square, pseudo, moves, own_king\n        )\n        if count == 0:\n            if has_any_legal_move_with_king(\n                board, side, castling, ep_square, pseudo, own_king\n            ):\n                flag = TT_EXACT if best_score > alpha_original else TT_UPPER\n                _qsearch_tt_store(\n                    current_key, current_tt_context, q_depth, -1, best_score, flag, ply, tt_table\n                )\n                return alpha, False\n            return 0, False\n        _order_moves(board, moves, count, tt_preferred, score_stack[ply])\n'''
new = '''    else:\n        own_king = int(\n            eval_stack[ply][EVAL_WHITE_KING]\n            if side == WHITE\n            else eval_stack[ply][EVAL_BLACK_KING]\n        )\n        if qply == 0:\n            # Bounded horizon repair: at the first qsearch ply only, admit legal quiet checks\n            # alongside captures/promotions. Quiet non-checks are discarded immediately after\n            # make, so deeper qsearch remains the existing tactical-only kernel.\n            count = _legal_moves_for_state(\n                board, side, castling, ep_square, pseudo, moves, eval_stack[ply]\n            )\n        else:\n            count = generate_legal_tactical_moves_into_with_king(\n                board, side, ep_square, pseudo, moves, own_king\n            )\n        if count == 0:\n            if qply == 0 or has_any_legal_move_with_king(\n                board, side, castling, ep_square, pseudo, own_king\n            ):\n                flag = TT_EXACT if best_score > alpha_original else TT_UPPER\n                _qsearch_tt_store(\n                    current_key, current_tt_context, q_depth, -1, best_score, flag, ply, tt_table\n                )\n                return alpha, False\n            return 0, False\n        _order_moves(board, moves, count, tt_preferred, score_stack[ply])\n'''
if s.count(old) != 1:
    raise SystemExit(f'qcheck0 generation patch mismatch: {s.count(old)}')
s = s.replace(old, new, 1)
old2 = '''        move = int(moves[index])\n        packed_order = int(score_stack[ply, index])\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(\n'''
new2 = '''        move = int(moves[index])\n        packed_order = int(score_stack[ply, index])\n        qcheck_quiet_candidate = (not checked and qply == 0 and not _is_tactical(board, move))\n        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(\n'''
if s.count(old2) != 1:
    raise SystemExit(f'qcheck0 loop patch mismatch: {s.count(old2)}')
s = s.replace(old2, new2, 1)
old3 = '''        history_contexts[ply + 1] = _child_history_context(\n            current_context, current_key, child_halfmove\n        )\n        score, aborted = _quiescence(\n'''
new3 = '''        history_contexts[ply + 1] = _child_history_context(\n            current_context, current_key, child_halfmove\n        )\n        if qcheck_quiet_candidate and not _state_in_check(board, -side, eval_stack[ply + 1]):\n            undo_move_inplace(board, side, move, captured_piece, captured_square)\n            continue\n        score, aborted = _quiescence(\n'''
if s.count(old3) != 1:
    raise SystemExit(f'qcheck0 check-filter patch mismatch: {s.count(old3)}')
s = s.replace(old3, new3, 1)
p.write_text(s)
