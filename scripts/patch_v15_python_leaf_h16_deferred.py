#!/usr/bin/env python3
"""Make leaf-H16 Gestalt exact-deferred instead of rebuilding every qsearch entry."""
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()

def r(old,new,label,n=1):
 c=s.count(old)
 if c!=n: raise SystemExit(f'{label}: expected {n}, found {c}')
 return s.replace(old,new,n)

# Build one valid H16 root row. The existing leaf scorer materializes the tail as a side effect.
s=r('''    # Rich student is leaf-materialized; ordinary search carries only the V13 prefix.\n''','''    # Seed one valid H16 ancestor; descendants are deferred until qsearch needs them.\n    _evaluate_gestalt_leaf(board, WHITE, state)\n''','root H16 seed')

anchor='''@njit(cache=False, inline="never")\ndef _advance_residual_state_into(\n'''
helper='''GESTALT_EDGE_INVALID = np.uint64(0x8000000000000000)\nGESTALT_EDGE_MOVE_MASK = np.uint64((1 << 18) - 1)\n\n@njit(cache=False, inline="always")\ndef _pack_gestalt_edge(move: int, moving_signed: int, captured_signed: int) -> np.uint64:\n    return (GESTALT_EDGE_INVALID | np.uint64(move & ((1 << 18) - 1))\n            | (np.uint64((moving_signed + 6) & 15) << np.uint64(18))\n            | (np.uint64((captured_signed + 6) & 15) << np.uint64(22)))\n\n@njit(cache=False, inline="always")\ndef _gestalt_feature(perspective: int, king_square: int, signed_piece: int, square: int) -> int:\n    mapped = king_square\n    if perspective != WHITE:\n        mapped = (king_square & 7) + (7 - (king_square >> 3)) * 8\n    bucket = int(GESTALT_BUCKET_MAP[mapped]) % 9\n    mirror = (king_square & 7) >= 4\n    file = square & 7; rank = square >> 3\n    if mirror: file = 7 - file\n    if perspective != WHITE: rank = 7 - rank\n    same = (signed_piece > 0) == (perspective == WHITE)\n    owner = 0 if same else 1\n    return bucket * 768 + (owner * 6 + abs(signed_piece) - 1) * 64 + rank * 8 + file\n\n@njit(cache=False, inline="always")\ndef _advance_gestalt_edge_into(edge: np.uint64, parent: np.ndarray, child: np.ndarray) -> None:\n    move=int(edge & GESTALT_EDGE_MOVE_MASK)\n    moving=int((edge >> np.uint64(18)) & np.uint64(15))-6\n    captured=int((edge >> np.uint64(22)) & np.uint64(15))-6\n    side=WHITE if moving>0 else -WHITE\n    frm=move_from(move); to=move_to(move); promo=move_promotion(move)\n    placed=side*promo if promo else moving\n    cap_sq=to-8*side if move & FLAG_EP else to\n    wk=int(parent[EVAL_WHITE_KING]); bk=int(parent[EVAL_BLACK_KING])\n    for lane in range(GESTALT_HIDDEN):\n        w=int(parent[GESTALT_WHITE_OFFSET+lane]); b=int(parent[GESTALT_BLACK_OFFSET+lane])\n        w-=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(WHITE,wk,moving,frm),lane])\n        b-=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(-WHITE,bk,moving,frm),lane])\n        if captured!=EMPTY:\n            w-=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(WHITE,wk,captured,cap_sq),lane])\n            b-=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(-WHITE,bk,captured,cap_sq),lane])\n        w+=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(WHITE,wk,placed,to),lane])\n        b+=int(GESTALT_FEATURE_WEIGHTS[_gestalt_feature(-WHITE,bk,placed,to),lane])\n        child[GESTALT_WHITE_OFFSET+lane]=w; child[GESTALT_BLACK_OFFSET+lane]=b\n\n@njit(cache=False, inline="always")\ndef _infer_gestalt_materialized(side: int, state: np.ndarray) -> int:\n    raw=np.int64(0)\n    for lane in range(GESTALT_HIDDEN):\n        w=int(state[GESTALT_WHITE_OFFSET+lane]); b=int(state[GESTALT_BLACK_OFFSET+lane])\n        if w<0: w=0\n        elif w>GESTALT_QA: w=GESTALT_QA\n        if b<0: b=0\n        elif b>GESTALT_QA: b=GESTALT_QA\n        us=w if side==WHITE else b; them=b if side==WHITE else w\n        raw += np.int64(us*us)*np.int64(GESTALT_OUTPUT_US[lane]) + np.int64(them*them)*np.int64(GESTALT_OUTPUT_THEM[lane])\n    cp=trunc_div_scalar(raw,GESTALT_QA)\n    cp=trunc_div_scalar(cp*GESTALT_CP_SCALE,GESTALT_QA*GESTALT_QB)\n    cp=trunc_div_scalar(cp,GESTALT_SCALE_DEN*GESTALT_RUNTIME_DEN)\n    return _evaluate_state_v13_only(side,state)+cp\n\n@njit(cache=False, inline="always")\ndef _materialize_gestalt_path(board: np.ndarray, eval_stack: np.ndarray, edges: np.ndarray, ply: int) -> None:\n    base=ply\n    while base>0 and (edges[base] & GESTALT_EDGE_INVALID)!=np.uint64(0): base-=1\n    level=base+1\n    while level<=ply:\n        edge=edges[level]\n        if (edge & GESTALT_EDGE_INVALID)!=np.uint64(0):\n            moving=int((edge >> np.uint64(18)) & np.uint64(15))-6\n            if abs(moving)==KING:\n                _evaluate_gestalt_leaf(board,WHITE,eval_stack[ply]); edges[ply]=np.uint64(0); return\n        level+=1\n    level=base+1\n    while level<=ply:\n        edge=edges[level]\n        if (edge & GESTALT_EDGE_INVALID)!=np.uint64(0):\n            _advance_gestalt_edge_into(edge,eval_stack[level-1],eval_stack[level]); edges[level]=np.uint64(0)\n        level+=1\n\n'''+anchor
s=r(anchor,helper,'helper')

s=r('''            stand_pat = _evaluate_gestalt_leaf(board, side, eval_stack[ply])\n''','''            stand_pat = _infer_gestalt_materialized(side, eval_stack[ply])\n''','qsearch inference')

sig='''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
sig2='''    history_contexts: np.ndarray,\n    gestalt_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
s=r(sig,sig2,'negamax signature')
s=r(sig.replace('tuple[int, bool]','tuple[int, int, bool]'),sig2.replace('tuple[int, bool]','tuple[int, int, bool]'),'root signature')
s=r('''    if depth <= 0:\n        return _quiescence(\n''','''    if depth <= 0:\n        _materialize_gestalt_path(board, eval_stack, gestalt_edges, ply)\n        return _quiescence(\n''','depth zero')

old='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n'''
new='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        moving_signed=int(board[move_from(move)])\n        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n        gestalt_edges[ply+1]=_pack_gestalt_edge(move,moving_signed,captured_piece)\n'''
s=r(old,new,'negamax edge')

root_start=s.index('def _root('); root_end=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(',root_start)
block=s[root_start:root_end]
old='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n'''
new='''        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1\n        moving_signed=int(board[move_from(move)])\n        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n        gestalt_edges[1]=_pack_gestalt_edge(move,moving_signed,captured_piece)\n'''
if block.count(old)!=1: raise SystemExit(f'root edge: {block.count(old)}')
block=block.replace(old,new,1); s=s[:root_start]+block+s[root_end:]

compact='path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,'
if s.count(compact)<7: raise SystemExit(f'calls: {s.count(compact)}')
s=s.replace(compact,'path_keys, killers, hash_keys, hash_moves, history_contexts, gestalt_edges, tt_table,')
s=s.replace('            history_contexts,\n            tt_table,\n','            history_contexts,\n            gestalt_edges,\n            tt_table,\n')
s=s.replace('            killers, hash_keys, hash_moves, history_contexts,\n            tt_table,\n','            killers, hash_keys, hash_moves, history_contexts, gestalt_edges,\n            tt_table,\n')
alloc='    history_contexts = np.empty(MAX_PLY, dtype=np.uint64)\n'
if s.count(alloc)!=3: raise SystemExit(f'edge alloc: {s.count(alloc)}')
s=s.replace(alloc,alloc+'    gestalt_edges = np.zeros(MAX_PLY, dtype=np.uint64)\n')
p.write_text(s)
# qualification-trigger touch
