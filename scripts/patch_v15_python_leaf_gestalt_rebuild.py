#!/usr/bin/env python3
from __future__ import annotations
import argparse
from pathlib import Path


def replace_exact(s: str, old: str, new: str, label: str, expected: int = 1) -> str:
    n=s.count(old)
    if n != expected:
        raise SystemExit(f'{label}: expected {expected}, found {n}')
    return s.replace(old,new,expected)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('path',type=Path)
    ap.add_argument('--extra-den',type=int,default=1)
    a=ap.parse_args()
    if a.extra_den not in (1,2,4,8): raise SystemExit('extra-den must be 1,2,4,8')
    p=a.path;s=p.read_text()
    if 'LEAF_GESTALT_HIDDEN' in s: raise SystemExit('already patched')

    model_anchor='''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n'''
    model_new=f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# V15 leaf-only Rust-Gestalt distillation.  This richer king-bucket model is rebuilt only at the\n# first non-check qsearch leaf, so ordinary negamax pays no dual-perspective accumulator cost.\n_leaf_gestalt_model = np.load(Path(__file__).with_name("v15_leaf_gestalt_h16.npz"), allow_pickle=False)\nLEAF_GESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(_leaf_gestalt_model["feature_weights"], dtype=np.int16)\nLEAF_GESTALT_FEATURE_BIAS = np.ascontiguousarray(_leaf_gestalt_model["feature_bias"], dtype=np.int16)\nLEAF_GESTALT_OUTPUT_US = np.ascontiguousarray(_leaf_gestalt_model["output_us"], dtype=np.int16)\nLEAF_GESTALT_OUTPUT_THEM = np.ascontiguousarray(_leaf_gestalt_model["output_them"], dtype=np.int16)\nLEAF_GESTALT_MODEL_DEN = int(np.asarray(_leaf_gestalt_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _leaf_gestalt_model\nLEAF_GESTALT_HIDDEN = 16\nLEAF_GESTALT_EXTRA_DEN = {a.extra_den}\nif LEAF_GESTALT_FEATURE_WEIGHTS.shape != (6912, LEAF_GESTALT_HIDDEN):\n    raise ValueError("invalid V15 leaf Gestalt feature matrix")\nif LEAF_GESTALT_FEATURE_BIAS.shape != (LEAF_GESTALT_HIDDEN,):\n    raise ValueError("invalid V15 leaf Gestalt bias")\nif LEAF_GESTALT_OUTPUT_US.shape != (LEAF_GESTALT_HIDDEN,) or LEAF_GESTALT_OUTPUT_THEM.shape != (LEAF_GESTALT_HIDDEN,):\n    raise ValueError("invalid V15 leaf Gestalt heads")\nif LEAF_GESTALT_MODEL_DEN <= 0:\n    raise ValueError("invalid V15 leaf Gestalt scale")\nLEAF_GESTALT_QA = 255\nLEAF_GESTALT_QB = 64\nLEAF_GESTALT_CP_SCALE = 400\nLEAF_GESTALT_BUCKET_MAP = np.asarray([\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13,\n    6,6,6,6,15,15,15,15, 7,7,7,7,16,16,16,16,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n], dtype=np.int16)\n'''
    s=replace_exact(s,model_anchor,model_new,'model anchor')

    layout='''STUDENT_OFFSET = EVAL_V13_WIDTH\nSTUDENT_HIDDEN = 64\nEVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN\n'''
    layout_new='''STUDENT_OFFSET = EVAL_V13_WIDTH\nSTUDENT_HIDDEN = 64\nEVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN\n# Reuse the already-allocated V14 tail row for two H16 perspective accumulators.\nLEAF_GESTALT_WHITE_OFFSET = STUDENT_OFFSET\nLEAF_GESTALT_BLACK_OFFSET = LEAF_GESTALT_WHITE_OFFSET + LEAF_GESTALT_HIDDEN\nLEAF_GESTALT_END = LEAF_GESTALT_BLACK_OFFSET + LEAF_GESTALT_HIDDEN\n'''
    s=replace_exact(s,layout,layout_new,'layout')

    old_build='''    build_absolute768_accumulator_into(\n        board,\n        STUDENT_FEATURE_WEIGHTS,\n        STUDENT_FEATURE_BIAS,\n        state[STUDENT_OFFSET:EVAL_WIDTH],\n    )\n'''
    s=replace_exact(s,old_build,'','remove eager H64 build')

    anchor='''@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    helpers='''@njit(cache=False, inline="always")\ndef _leaf_gestalt_feature_index(perspective: int, king_square: int, signed_piece: int, square: int) -> int:\n    king_file = king_square & 7\n    mapped_king = king_square if perspective == WHITE else (king_file + (7 - (king_square >> 3)) * 8)\n    bucket = int(LEAF_GESTALT_BUCKET_MAP[mapped_king]) % 9\n    mirror = king_file >= 4\n    file = square & 7\n    rank = square >> 3\n    if mirror:\n        file = 7 - file\n    if perspective != WHITE:\n        rank = 7 - rank\n    same_owner = (signed_piece > 0) == (perspective == WHITE)\n    ownership = 0 if same_owner else 1\n    plane = ownership * 6 + (abs(signed_piece) - 1)\n    return bucket * 768 + plane * 64 + rank * 8 + file\n\n\n@njit(cache=False, inline="always")\ndef _build_leaf_gestalt_into(board: np.ndarray, state: np.ndarray) -> None:\n    white = state[LEAF_GESTALT_WHITE_OFFSET:LEAF_GESTALT_BLACK_OFFSET]\n    black = state[LEAF_GESTALT_BLACK_OFFSET:LEAF_GESTALT_END]\n    for lane in range(LEAF_GESTALT_HIDDEN):\n        bias = int(LEAF_GESTALT_FEATURE_BIAS[lane])\n        white[lane] = bias\n        black[lane] = bias\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    for square in range(64):\n        signed_piece = int(board[square])\n        if signed_piece == EMPTY:\n            continue\n        wi = _leaf_gestalt_feature_index(WHITE, white_king, signed_piece, square)\n        bi = _leaf_gestalt_feature_index(-WHITE, black_king, signed_piece, square)\n        for lane in range(LEAF_GESTALT_HIDDEN):\n            white[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[wi, lane])\n            black[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[bi, lane])\n\n\n@njit(cache=False, inline="always")\ndef _infer_leaf_gestalt_cp(side: int, state: np.ndarray) -> int:\n    raw = np.int64(0)\n    for lane in range(LEAF_GESTALT_HIDDEN):\n        w = int(state[LEAF_GESTALT_WHITE_OFFSET + lane])\n        b = int(state[LEAF_GESTALT_BLACK_OFFSET + lane])\n        if w < 0:\n            w = 0\n        elif w > LEAF_GESTALT_QA:\n            w = LEAF_GESTALT_QA\n        if b < 0:\n            b = 0\n        elif b > LEAF_GESTALT_QA:\n            b = LEAF_GESTALT_QA\n        if side == WHITE:\n            us, them = w, b\n        else:\n            us, them = b, w\n        raw += np.int64(us * us) * np.int64(LEAF_GESTALT_OUTPUT_US[lane])\n        raw += np.int64(them * them) * np.int64(LEAF_GESTALT_OUTPUT_THEM[lane])\n    scaled = trunc_div_scalar(raw, LEAF_GESTALT_QA)\n    cp = trunc_div_scalar(scaled * LEAF_GESTALT_CP_SCALE, LEAF_GESTALT_QA * LEAF_GESTALT_QB)\n    return trunc_div_scalar(cp, LEAF_GESTALT_MODEL_DEN * LEAF_GESTALT_EXTRA_DEN)\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_leaf_gestalt(side: int, state: np.ndarray) -> int:\n    return _evaluate_state_v13_only(side, state) + _infer_leaf_gestalt_cp(side, state)\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    s=replace_exact(s,anchor,helpers,'helper anchor')

    old='''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n'''
    new='''        if qply == 0:\n            _build_leaf_gestalt_into(board, eval_stack[ply])\n            stand_pat = _evaluate_state_leaf_gestalt(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n'''
    s=replace_exact(s,old,new,'qsearch standpat')

    old_transport='''        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])\n'''
    new_transport='''        _advance_eval_state_into(\n            board, side, move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n'''
    s=replace_exact(s,old_transport,new_transport,'negamax transport')
    old_root='''        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n'''
    new_root='''        _advance_eval_state_into(\n            board, side, move,\n            eval_stack[0, :EVAL_V13_WIDTH],\n            eval_stack[1, :EVAL_V13_WIDTH],\n        )\n'''
    s=replace_exact(s,old_root,new_root,'root/fallback transports',expected=4)

    fallback='''                fallback_score = -_evaluate_state(-side, eval_stack[1])\n'''
    fallback_new='''                _build_leaf_gestalt_into(board, eval_stack[1])\n                fallback_score = -_evaluate_state_leaf_gestalt(-side, eval_stack[1])\n'''
    s=replace_exact(s,fallback,fallback_new,'fallback eval',expected=3)

    p.write_text(s)

if __name__=='__main__': main()
