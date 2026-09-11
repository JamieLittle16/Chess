#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit('usage: apply_v18_root_static_regularizer.py SEARCH.py DIVISOR')
p=Path(sys.argv[1]); divisor=int(sys.argv[2])
if divisor < 2 or divisor > 12: raise SystemExit('DIVISOR must be 2..12')
s=p.read_text()
old='''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        if score > best_score:\n'''
new=f'''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        # Root-only structural regularizer for ordinary quiet moves. Deep search remains the\n        # dominant term; this only prevents a small searched edge from completely overriding a\n        # clear one-ply structural signal from the same evaluator. Never touch tactical/mating\n        # scores, captures, promotions, or en-passant moves.\n        if (packed_order & 3) == 0 and abs(score) < MATE_THRESHOLD:\n            child_root_static = -_evaluate_state(-side, eval_stack[1])\n            static_delta = child_root_static - root_static\n            if static_delta > 120:\n                static_delta = 120\n            elif static_delta < -120:\n                static_delta = -120\n            if static_delta >= 0:\n                score += static_delta // {divisor}\n            else:\n                score -= (-static_delta) // {divisor}\n        if score > best_score:\n'''
if s.count(old) != 1: raise SystemExit(f'root regularizer patch mismatch: {s.count(old)}')
p.write_text(s.replace(old,new,1))
