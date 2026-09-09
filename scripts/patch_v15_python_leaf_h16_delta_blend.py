#!/usr/bin/env python3
"""Blend king-bucket H16 Rust-Gestalt knowledge into V14 at qsearch stand-pat.

Unlike full evaluator replacement, this keeps the accepted V14 evaluation and adds only a fraction
of the difference between the search-leaf H16 student's Rust-Gestalt correction and V14's H64
correction, both measured relative to the identical V13 base:

    eval = V14 + blend * (H16_correction - H64_correction)

The H16 accumulator is reconstructed only at qply==0.  Its 32 live perspective lanes reuse the
qsearch pseudo-move buffer before move generation, so no extra search-stack array or per-leaf heap
allocation is required.  Apply after the qualified exact-speed stack.
"""
from __future__ import annotations
import argparse
from pathlib import Path


def one(s:str,old:str,new:str,label:str)->str:
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1, found {n}')
    return s.replace(old,new,1)


def patch(path:Path,num:int,den:int)->None:
    if num<=0 or den<=0 or num>den: raise SystemExit('blend must satisfy 0<num<=den')
    s=path.read_text()
    if 'LEAF_GESTALT_HIDDEN' in s: raise SystemExit('H16 delta blend already present')
    anchor='STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n'
    load=f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# Search-leaf H16 Rust-Gestalt distillation.  This is a correction relative to the same V13 base\n# used by V14 H64, making delta blending well-defined.\n_leaf_gestalt_model = np.load(Path(__file__).with_name("v15_gestalt_h16.npz"), allow_pickle=False)\nLEAF_GESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(_leaf_gestalt_model["feature_weights"], dtype=np.int16)\nLEAF_GESTALT_FEATURE_BIAS = np.ascontiguousarray(_leaf_gestalt_model["feature_bias"], dtype=np.int16)\nLEAF_GESTALT_OUTPUT_US = np.ascontiguousarray(_leaf_gestalt_model["output_us"], dtype=np.int16)\nLEAF_GESTALT_OUTPUT_THEM = np.ascontiguousarray(_leaf_gestalt_model["output_them"], dtype=np.int16)\nLEAF_GESTALT_MODEL_DEN = int(np.asarray(_leaf_gestalt_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _leaf_gestalt_model\nLEAF_GESTALT_HIDDEN = 16\nLEAF_GESTALT_QA = 255\nLEAF_GESTALT_QB = 64\nLEAF_GESTALT_CP_SCALE = 400\nLEAF_GESTALT_BLEND_NUM = {num}\nLEAF_GESTALT_BLEND_DEN = {den}\nif LEAF_GESTALT_FEATURE_WEIGHTS.shape != (6912, LEAF_GESTALT_HIDDEN):\n    raise ValueError("invalid leaf H16 Gestalt feature matrix")\nif LEAF_GESTALT_FEATURE_BIAS.shape != (LEAF_GESTALT_HIDDEN,):\n    raise ValueError("invalid leaf H16 Gestalt feature bias")\nif LEAF_GESTALT_OUTPUT_US.shape != (LEAF_GESTALT_HIDDEN,) or LEAF_GESTALT_OUTPUT_THEM.shape != (LEAF_GESTALT_HIDDEN,):\n    raise ValueError("invalid leaf H16 Gestalt output head")\nif LEAF_GESTALT_MODEL_DEN <= 0:\n    raise ValueError("invalid leaf H16 Gestalt denominator")\nLEAF_GESTALT_BUCKET_MAP = np.asarray((\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n), dtype=np.int16)\n'''
    s=one(s,anchor,load,'model load')
    anchor='''@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    helper='''@njit(cache=False, inline="always")\ndef _leaf_gestalt_bucket(king_square: int, perspective: int) -> int:\n    mapped = king_square\n    if perspective != WHITE:\n        mapped = (king_square & 7) + (7 - (king_square >> 3)) * 8\n    return int(LEAF_GESTALT_BUCKET_MAP[mapped]) % 9\n\n\n@njit(cache=False, inline="never")\ndef _leaf_gestalt_h16_correction_cp(\n    board: np.ndarray, side: int, state: np.ndarray, scratch: np.ndarray\n) -> int:\n    # scratch is pseudo_stack[ply] before qsearch move generation.  First 16 lanes are White POV,\n    # next 16 Black POV; move generation is free to overwrite them immediately afterwards.\n    for lane in range(LEAF_GESTALT_HIDDEN):\n        bias = int(LEAF_GESTALT_FEATURE_BIAS[lane])\n        scratch[lane] = bias\n        scratch[LEAF_GESTALT_HIDDEN + lane] = bias\n\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    white_bucket = _leaf_gestalt_bucket(white_king, WHITE)\n    black_bucket = _leaf_gestalt_bucket(black_king, -WHITE)\n    white_mirror = (white_king & 7) >= 4\n    black_mirror = (black_king & 7) >= 4\n\n    for square in range(64):\n        signed_piece = int(board[square])\n        if signed_piece == EMPTY:\n            continue\n        plane = abs(signed_piece) - 1\n        file = square & 7\n        rank = square >> 3\n        wf = 7 - file if white_mirror else file\n        bf = 7 - file if black_mirror else file\n        white_owner = 0 if signed_piece > 0 else 1\n        black_owner = 0 if signed_piece < 0 else 1\n        fw = white_bucket * 768 + (white_owner * 6 + plane) * 64 + rank * 8 + wf\n        fb = black_bucket * 768 + (black_owner * 6 + plane) * 64 + (7 - rank) * 8 + bf\n        for lane in range(LEAF_GESTALT_HIDDEN):\n            scratch[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[fw, lane])\n            scratch[LEAF_GESTALT_HIDDEN + lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[fb, lane])\n\n    raw = np.int64(0)\n    for lane in range(LEAF_GESTALT_HIDDEN):\n        w = int(scratch[lane]); b = int(scratch[LEAF_GESTALT_HIDDEN + lane])\n        if w < 0: w = 0\n        elif w > LEAF_GESTALT_QA: w = LEAF_GESTALT_QA\n        if b < 0: b = 0\n        elif b > LEAF_GESTALT_QA: b = LEAF_GESTALT_QA\n        if side == WHITE: us, them = w, b\n        else: us, them = b, w\n        raw += np.int64(us * us) * np.int64(LEAF_GESTALT_OUTPUT_US[lane])\n        raw += np.int64(them * them) * np.int64(LEAF_GESTALT_OUTPUT_THEM[lane])\n    cp = trunc_div_scalar(int(raw), LEAF_GESTALT_QA)\n    cp = trunc_div_scalar(cp * LEAF_GESTALT_CP_SCALE, LEAF_GESTALT_QA * LEAF_GESTALT_QB)\n    return trunc_div_scalar(cp, LEAF_GESTALT_MODEL_DEN)\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    s=one(s,anchor,helper,'helper anchor')
    old='''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n'''
    new='''        if qply == 0:\n            v14_eval = _evaluate_state(side, eval_stack[ply])\n            v13_eval = _evaluate_state_v13_only(side, eval_stack[ply])\n            h64_correction = v14_eval - v13_eval\n            h16_correction = _leaf_gestalt_h16_correction_cp(\n                board, side, eval_stack[ply], pseudo_stack[ply]\n            )\n            correction_delta = h16_correction - h64_correction\n            stand_pat = v14_eval + trunc_div_scalar(\n                correction_delta * LEAF_GESTALT_BLEND_NUM, LEAF_GESTALT_BLEND_DEN\n            )\n        else:\n'''
    s=one(s,old,new,'qsearch stand-pat')
    path.write_text(s)


def main()->int:
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('path',type=Path);ap.add_argument('--blend-num',type=int,required=True);ap.add_argument('--blend-den',type=int,required=True);a=ap.parse_args();patch(a.path,a.blend_num,a.blend_den);return 0
if __name__=='__main__': raise SystemExit(main())
