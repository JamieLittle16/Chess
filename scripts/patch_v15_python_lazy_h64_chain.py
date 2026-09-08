#!/usr/bin/env python3
"""Defer interior H64 transport and materialize exact delta chains only at qsearch entry."""
from pathlib import Path
import sys
if len(sys.argv)!=2: raise SystemExit('usage: patch_v15_python_lazy_h64_chain.py numba_search.py')
p=Path(sys.argv[1]);s=p.read_text()
anchor='''@njit(cache=False, inline="always")\ndef _repetition_piece_index(signed_piece: int) -> int:\n'''
helper='''STUDENT_EDGE_INVALID = np.uint64(0x8000000000000000)\nSTUDENT_EDGE_MOVE_MASK = np.uint64((1 << 18) - 1)\n\n\n@njit(cache=False, inline="always")\ndef _pack_student_edge(move: int, moving_signed: int, captured_signed: int) -> np.uint64:\n    return (STUDENT_EDGE_INVALID | np.uint64(move & ((1 << 18) - 1))\n        | (np.uint64((moving_signed + 6) & 15) << np.uint64(18))\n        | (np.uint64((captured_signed + 6) & 15) << np.uint64(22)))\n\n\n@njit(cache=False, inline="always")\ndef _advance_student_edge_into(edge: np.uint64, parent: np.ndarray, child: np.ndarray) -> None:\n    move = int(edge & STUDENT_EDGE_MOVE_MASK)\n    moving_signed = int((edge >> np.uint64(18)) & np.uint64(15)) - 6\n    captured_signed = int((edge >> np.uint64(22)) & np.uint64(15)) - 6\n    side = WHITE if moving_signed > 0 else -WHITE\n    from_square = move_from(move); to_square = move_to(move); promotion = move_promotion(move)\n    placed_signed = side * promotion if promotion else moving_signed\n    from_feature = (0 if moving_signed > 0 else 384) + (abs(moving_signed)-1)*64 + from_square\n    to_feature = (0 if placed_signed > 0 else 384) + (abs(placed_signed)-1)*64 + to_square\n    captured_feature = -1\n    if captured_signed != EMPTY:\n        captured_square = to_square - 8*side if move & FLAG_EP else to_square\n        captured_feature = (0 if captured_signed > 0 else 384) + (abs(captured_signed)-1)*64 + captured_square\n    rook_from_feature = -1; rook_to_feature = -1\n    if move & FLAG_CASTLE:\n        if to_square == 6: rook_from,rook_to=7,5\n        elif to_square == 2: rook_from,rook_to=0,3\n        elif to_square == 62: rook_from,rook_to=63,61\n        else: rook_from,rook_to=56,59\n        rook_signed=side*ROOK\n        rook_from_feature=(0 if rook_signed>0 else 384)+(ROOK-1)*64+rook_from\n        rook_to_feature=(0 if rook_signed>0 else 384)+(ROOK-1)*64+rook_to\n    for neuron in range(STUDENT_HIDDEN):\n        value=int(parent[neuron])\n        value-=int(STUDENT_FEATURE_WEIGHTS[from_feature,neuron])\n        if captured_feature>=0: value-=int(STUDENT_FEATURE_WEIGHTS[captured_feature,neuron])\n        value+=int(STUDENT_FEATURE_WEIGHTS[to_feature,neuron])\n        if rook_from_feature>=0:\n            value-=int(STUDENT_FEATURE_WEIGHTS[rook_from_feature,neuron]); value+=int(STUDENT_FEATURE_WEIGHTS[rook_to_feature,neuron])\n        child[neuron]=value\n\n\n@njit(cache=False, inline="always")\ndef _materialize_student_path(eval_stack: np.ndarray, student_edges: np.ndarray, ply: int) -> None:\n    base=ply\n    while base>0 and (student_edges[base] & STUDENT_EDGE_INVALID)!=np.uint64(0): base-=1\n    level=base+1\n    while level<=ply:\n        edge=student_edges[level]\n        if (edge & STUDENT_EDGE_INVALID)!=np.uint64(0):\n            _advance_student_edge_into(edge,eval_stack[level-1,STUDENT_OFFSET:EVAL_WIDTH],eval_stack[level,STUDENT_OFFSET:EVAL_WIDTH])\n            student_edges[level]=np.uint64(0)\n        level+=1\n\n\n@njit(cache=False, inline="always")\ndef _repetition_piece_index(signed_piece: int) -> int:\n'''
if s.count(anchor)!=1: raise SystemExit(f'helper anchor count={s.count(anchor)}')
s=s.replace(anchor,helper,1)
sig='''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''; rep='''    history_contexts: np.ndarray,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:'''
if s.count(sig)!=1: raise SystemExit(f'negamax signature anchor count={s.count(sig)}')
s=s.replace(sig,rep,1)
sig='''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:'''; rep='''    history_contexts: np.ndarray,\n    student_edges: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:'''
if s.count(sig)!=1: raise SystemExit(f'root signature anchor count={s.count(sig)}')
s=s.replace(sig,rep,1)
old='''    if depth <= 0:\n        return _quiescence(\n'''; new='''    if depth <= 0:\n        _materialize_student_path(eval_stack, student_edges, ply)\n        return _quiescence(\n'''
if s.count(old)!=1: raise SystemExit(f'depth-zero anchor count={s.count(old)}')
s=s.replace(old,new,1)
start=s.index('def _negamax(');end=s.index('\n\n\n@njit(cache=False)\ndef _root(',start);block=s[start:end]
old='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n'''
new='''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n        moving_signed = int(board[move_from(move)])\n        _advance_eval_state_into(board, side, move, eval_stack[ply, :EVAL_V13_WIDTH], eval_stack[ply + 1, :EVAL_V13_WIDTH])\n        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(\n            board, side, castling, ep_square, move\n        )\n        student_edges[ply + 1] = _pack_student_edge(move, moving_signed, captured_piece)\n'''
if block.count(old)!=1: raise SystemExit(f'negamax transport anchor count={block.count(old)}')
block=block.replace(old,new,1)
oldtail='''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,\n''';newtail='''                path_keys, killers, hash_keys, hash_moves, history_contexts, student_edges, tt_table,\n'''
if block.count(oldtail)!=4: raise SystemExit(f'negamax recursive tail count={block.count(oldtail)}')
block=block.replace(oldtail,newtail);s=s[:start]+block+s[end:]
start=s.index('def _root(');end=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(',start);block=s[start:end]
if block.count(oldtail)!=3: raise SystemExit(f'root negamax tail count={block.count(oldtail)}')
block=block.replace(oldtail,newtail);s=s[:start]+block+s[end:]
old='''    history_contexts = np.empty(MAX_PLY, dtype=np.uint64)\n    history_contexts[0] = _root_history_context(history_keys, history_count)\n''';new='''    history_contexts = np.empty(MAX_PLY, dtype=np.uint64)\n    history_contexts[0] = _root_history_context(history_keys, history_count)\n    student_edges = np.zeros(MAX_PLY, dtype=np.uint64)\n'''
if s.count(old)!=3: raise SystemExit(f'entry allocation anchor count={s.count(old)}')
s=s.replace(old,new)
old='''            hash_moves,\n            history_contexts,\n            tt_table,\n''';new='''            hash_moves,\n            history_contexts,\n            student_edges,\n            tt_table,\n'''
if s.count(old)!=1: raise SystemExit(f'expanded root tail count={s.count(old)}')
s=s.replace(old,new,1)
old='''            killers, hash_keys, hash_moves, history_contexts,\n            tt_table,\n''';new='''            killers, hash_keys, hash_moves, history_contexts, student_edges,\n            tt_table,\n'''
if s.count(old)!=2: raise SystemExit(f'compact root tail count={s.count(old)}')
s=s.replace(old,new)
p.write_text(s)
