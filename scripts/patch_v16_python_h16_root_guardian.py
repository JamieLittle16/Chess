#!/usr/bin/env python3
"""Add a weak Rust-Gestalt H16 signal only to root move selection.

Raw search scores still drive PVS/alpha, TT, pruning, and all recursive search.  The guardian is
computed on the already-made root child and only ranks fully searched root moves.  This isolates the
useful defensive signal seen in Round 61 without replacing V14's calibrated leaf evaluator.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]); den=int(sys.argv[2]); s=p.read_text()
if den <= 0: raise SystemExit('guardian denominator must be positive')

model_anchor='''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n'''
model_insert=f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n_guardian_model = np.load(Path(__file__).with_name("v16_guardian_h16.npz"), allow_pickle=False)\nGUARDIAN_FEATURE_WEIGHTS = np.ascontiguousarray(_guardian_model["feature_weights"], dtype=np.int16)\nGUARDIAN_FEATURE_BIAS = np.ascontiguousarray(_guardian_model["feature_bias"], dtype=np.int16)\nGUARDIAN_OUTPUT_US = np.ascontiguousarray(_guardian_model["output_us"], dtype=np.int16)\nGUARDIAN_OUTPUT_THEM = np.ascontiguousarray(_guardian_model["output_them"], dtype=np.int16)\nGUARDIAN_SCALE_DEN = int(np.asarray(_guardian_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _guardian_model\nGUARDIAN_HIDDEN = 16\nROOT_GUARDIAN_DEN = {den}\nGUARDIAN_BUCKET_MAP = np.asarray((\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17), dtype=np.int16)\nif GUARDIAN_FEATURE_WEIGHTS.shape != (6912, GUARDIAN_HIDDEN):\n    raise ValueError("invalid H16 guardian feature matrix")\n'''
if s.count(model_anchor)!=1: raise SystemExit(f'model anchor={s.count(model_anchor)}')
s=s.replace(model_anchor,model_insert,1)

root_anchor='''@njit(cache=False)\ndef _root(\n'''
helper='''@njit(cache=False, inline="always")\ndef _guardian_feature_index(perspective: int, king_square: int, signed_piece: int, square: int) -> int:\n    mapped = king_square\n    if perspective != WHITE:\n        mapped = (king_square & 7) + (7 - (king_square >> 3)) * 8\n    bucket = int(GUARDIAN_BUCKET_MAP[mapped]) % 9\n    mirror = (king_square & 7) >= 4\n    file = square & 7\n    rank = square >> 3\n    if mirror:\n        file = 7 - file\n    if perspective != WHITE:\n        rank = 7 - rank\n    same_owner = (signed_piece > 0) == (perspective == WHITE)\n    ownership = 0 if same_owner else 1\n    plane = ownership * 6 + abs(signed_piece) - 1\n    return bucket * 768 + plane * 64 + rank * 8 + file\n\n\n@njit(cache=False, inline="never")\ndef _root_guardian_correction(board: np.ndarray, side: int, state: np.ndarray) -> int:\n    white = np.empty(GUARDIAN_HIDDEN, dtype=np.int64)\n    black = np.empty(GUARDIAN_HIDDEN, dtype=np.int64)\n    for lane in range(GUARDIAN_HIDDEN):\n        bias = int(GUARDIAN_FEATURE_BIAS[lane])\n        white[lane] = bias\n        black[lane] = bias\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    for square in range(64):\n        piece = int(board[square])\n        if piece == EMPTY:\n            continue\n        wf = _guardian_feature_index(WHITE, white_king, piece, square)\n        bf = _guardian_feature_index(-WHITE, black_king, piece, square)\n        for lane in range(GUARDIAN_HIDDEN):\n            white[lane] += int(GUARDIAN_FEATURE_WEIGHTS[wf, lane])\n            black[lane] += int(GUARDIAN_FEATURE_WEIGHTS[bf, lane])\n    raw = np.int64(0)\n    for lane in range(GUARDIAN_HIDDEN):\n        w = int(white[lane]); b = int(black[lane])\n        if w < 0: w = 0\n        elif w > 255: w = 255\n        if b < 0: b = 0\n        elif b > 255: b = 255\n        us = w if side == WHITE else b\n        them = b if side == WHITE else w\n        raw += np.int64(us * us) * np.int64(GUARDIAN_OUTPUT_US[lane])\n        raw += np.int64(them * them) * np.int64(GUARDIAN_OUTPUT_THEM[lane])\n    cp = trunc_div_scalar(raw, 255)\n    cp = trunc_div_scalar(cp * 400, 255 * 64)\n    return trunc_div_scalar(cp, GUARDIAN_SCALE_DEN)\n\n\n'''+root_anchor
if s.count(root_anchor)!=1: raise SystemExit(f'root anchor={s.count(root_anchor)}')
s=s.replace(root_anchor,helper,1)

start=s.index('def _root(')
end=s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(',start)
root=s[start:end]
old='''    best_move = int(moves[0])\n    best_score = -INFINITY\n    alpha = -INFINITY\n'''
new='''    best_move = int(moves[0])\n    best_score = -INFINITY\n    best_selection_score = -INFINITY\n    alpha = -INFINITY\n'''
if root.count(old)!=1: raise SystemExit(f'root init={root.count(old)}')
root=root.replace(old,new,1)
old='''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        if score > best_score:\n            best_score = score\n            best_move = move\n        if score > alpha:\n            alpha = score\n'''
new='''        guardian_bonus = 0\n        if not aborted and depth >= 3:\n            # H16 returns child-side correction; negate it back to root perspective.\n            guardian_bonus = -_root_guardian_correction(board, -side, eval_stack[1])\n        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if aborted:\n            return best_move, best_score, True\n        score = -score\n        selection_score = score + trunc_div_scalar(guardian_bonus, ROOT_GUARDIAN_DEN)\n        if selection_score > best_selection_score:\n            best_selection_score = selection_score\n            best_score = score\n            best_move = move\n        if score > alpha:\n            alpha = score\n'''
if root.count(old)!=1: raise SystemExit(f'root selection={root.count(old)}')
root=root.replace(old,new,1)
s=s[:start]+root+s[end:]
p.write_text(s)
