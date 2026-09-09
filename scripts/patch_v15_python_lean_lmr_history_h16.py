#!/usr/bin/env python3
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text(); threshold=int(sys.argv[2]) if len(sys.argv)>2 else 2048

def r(old,new,label,n=1):
 c=s.count(old)
 if c!=n: raise SystemExit(f'{label}: expected {n}, found {c}')
 return s.replace(old,new,n)

s=r(s,'MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n',f'''MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\nLEAN_LMR_HISTORY_LIMIT = 16384\nLEAN_LMR_HISTORY_MAX_UPDATE = 2048\nLEAN_LMR_HISTORY_THRESHOLD = {threshold}\n''','constants')
anchor='''@njit(cache=False, inline="always")\ndef _lmr_v3_reduction(depth: int, move_index: int) -> int:\n'''
helper='''@njit(cache=False, inline="always")\ndef _lean_hist_update(current: int, bonus: int) -> int:\n    bonus=max(-2048,min(2048,bonus)); product=current*abs(bonus)\n    gravity=product//16384 if product>=0 else -((-product)//16384)\n    return max(-16384,min(16384,current+bonus-gravity))\n\n@njit(cache=False, inline="always")\ndef _lean_hist_reduction(depth: int, move_index: int, hist: int) -> int:\n    base=_lmr_v3_reduction(depth,move_index)\n    if hist>=LEAN_LMR_HISTORY_THRESHOLD: return max(0,base-1)\n    if hist<=-LEAN_LMR_HISTORY_THRESHOLD and depth>=5 and move_index>=4: return min(3,base+1)\n    return base\n\n'''+anchor
s=r(s,anchor,helper,'helper')
old='''    path_keys: np.ndarray,\n    killers: np.ndarray,\n    hash_keys: np.ndarray,\n    hash_moves: np.ndarray,\n    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
new=old.replace('    hash_keys: np.ndarray,','    lmr_history: np.ndarray,\n    hash_keys: np.ndarray,')
s=r(s,old,new,'negamax signature')
oldr=old.replace('tuple[int, bool]','tuple[int, int, bool]'); newr=new.replace('tuple[int, bool]','tuple[int, int, bool]')
s=r(s,oldr,newr,'root signature')
s=r(s,'    alpha_original = alpha\n    pseudo = pseudo_stack[ply]\n','    alpha_original = alpha\n    scout_node = beta == alpha + 1\n    pseudo = pseudo_stack[ply]\n','scout')
old='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n'''
new='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        moving_signed=int(board[move_from(move)])\n        hist_ctx=-1; hist_score=0\n        if quiet:\n            hist_ctx=(abs(moving_signed)-1)*64+move_to(move)\n            hist_side=0 if side==WHITE else 1\n            hist_score=int(lmr_history[hist_side,hist_ctx])\n        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n'''
s=r(s,old,new,'history context')
s=r(s,'        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0\n','        reduction = _lean_hist_reduction(depth,index,hist_score) if lmr_candidate else 0\n','lmr')
old='''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if score > best_score:\n'''
new='''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if quiet and scout_node and hist_ctx>=0:\n            bonus=min(2048,32*depth*depth+64*depth)\n            requested=bonus if score>=beta else -(bonus//2)\n            hist_side=0 if side==WHITE else 1\n            lmr_history[hist_side,hist_ctx]=_lean_hist_update(int(lmr_history[hist_side,hist_ctx]),requested)\n        if score > best_score:\n'''
s=r(s,old,new,'train')
compact='path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,'
if s.count(compact)<7: raise SystemExit(f'calls: {s.count(compact)}')
s=s.replace(compact,'path_keys, killers, lmr_history, hash_keys, hash_moves, history_contexts, tt_table,')
s=s.replace('            killers,\n            hash_keys,\n','            killers,\n            lmr_history,\n            hash_keys,\n')
s=s.replace('            killers, hash_keys, hash_moves, history_contexts,\n','            killers, lmr_history, hash_keys, hash_moves, history_contexts,\n')
alloc='    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)\n'
if s.count(alloc)!=3: raise SystemExit(f'alloc: {s.count(alloc)}')
s=s.replace(alloc,alloc+'    lmr_history = np.zeros((2, 384), dtype=np.int16)\n')
p.write_text(s)
