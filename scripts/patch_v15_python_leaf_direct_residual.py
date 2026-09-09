#!/usr/bin/env python3
"""Add a tiny king-bucket Gestalt-minus-V14 residual at first qsearch stand-pat.

Requires `v15_gestalt_residual.npz` beside numba_search.py.  The accepted V14 evaluator remains the
base.  At qply==0 only, the residual student rebuilds White/Black king-conditioned accumulators into
the existing pseudo-move scratch buffer and adds its calibrated cp correction.  Ordinary negamax,
V14 H64 transport, qsearch below qply 0, move ordering and TT semantics are otherwise unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1, found {count}')
    return source.replace(old, new, 1)


def patch(path: Path, cap_cp: int) -> None:
    if cap_cp < 0:
        raise SystemExit('cap-cp must be >= 0')
    s = path.read_text()
    if 'DIRECT_RESIDUAL_HIDDEN' in s:
        raise SystemExit('direct residual already present')

    anchor = 'STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n'
    load = f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# Direct Rust-Gestalt minus V14 residual.  It is evaluated only at first qsearch stand-pat.\n_direct_residual_model = np.load(Path(__file__).with_name("v15_gestalt_residual.npz"), allow_pickle=False)\nDIRECT_RESIDUAL_FEATURE_WEIGHTS = np.ascontiguousarray(_direct_residual_model["feature_weights"], dtype=np.int16)\nDIRECT_RESIDUAL_FEATURE_BIAS = np.ascontiguousarray(_direct_residual_model["feature_bias"], dtype=np.int16)\nDIRECT_RESIDUAL_OUTPUT_US = np.ascontiguousarray(_direct_residual_model["output_us"], dtype=np.int16)\nDIRECT_RESIDUAL_OUTPUT_THEM = np.ascontiguousarray(_direct_residual_model["output_them"], dtype=np.int16)\nDIRECT_RESIDUAL_MODEL_DEN = int(np.asarray(_direct_residual_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _direct_residual_model\nDIRECT_RESIDUAL_HIDDEN = int(DIRECT_RESIDUAL_FEATURE_WEIGHTS.shape[1])\nDIRECT_RESIDUAL_QA = 255\nDIRECT_RESIDUAL_QB = 64\nDIRECT_RESIDUAL_CP_SCALE = 400\nDIRECT_RESIDUAL_CAP_CP = {cap_cp}\nif DIRECT_RESIDUAL_HIDDEN not in (8, 12, 16):\n    raise ValueError("invalid direct residual hidden width")\nif DIRECT_RESIDUAL_FEATURE_WEIGHTS.shape[0] != 6912:\n    raise ValueError("invalid direct residual feature rows")\nif DIRECT_RESIDUAL_FEATURE_BIAS.shape != (DIRECT_RESIDUAL_HIDDEN,):\n    raise ValueError("invalid direct residual bias")\nif DIRECT_RESIDUAL_OUTPUT_US.shape != (DIRECT_RESIDUAL_HIDDEN,) or DIRECT_RESIDUAL_OUTPUT_THEM.shape != (DIRECT_RESIDUAL_HIDDEN,):\n    raise ValueError("invalid direct residual output")\nif DIRECT_RESIDUAL_MODEL_DEN <= 0:\n    raise ValueError("invalid direct residual denominator")\nDIRECT_RESIDUAL_BUCKET_MAP = np.asarray((\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n), dtype=np.int16)\n'''
    s = one(s, anchor, load, 'model load')

    anchor = '''@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    helper = '''@njit(cache=False, inline="always")\ndef _direct_residual_bucket(king_square: int, perspective: int) -> int:\n    mapped = king_square\n    if perspective != WHITE:\n        mapped = (king_square & 7) + (7 - (king_square >> 3)) * 8\n    return int(DIRECT_RESIDUAL_BUCKET_MAP[mapped]) % 9\n\n\n@njit(cache=False, inline="never")\ndef _direct_residual_cp(\n    board: np.ndarray, side: int, state: np.ndarray, scratch: np.ndarray\n) -> int:\n    hidden = DIRECT_RESIDUAL_HIDDEN\n    for lane in range(hidden):\n        bias = int(DIRECT_RESIDUAL_FEATURE_BIAS[lane])\n        scratch[lane] = bias\n        scratch[hidden + lane] = bias\n\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    white_bucket = _direct_residual_bucket(white_king, WHITE)\n    black_bucket = _direct_residual_bucket(black_king, -WHITE)\n    white_mirror = (white_king & 7) >= 4\n    black_mirror = (black_king & 7) >= 4\n\n    for square in range(64):\n        signed_piece = int(board[square])\n        if signed_piece == EMPTY:\n            continue\n        plane = abs(signed_piece) - 1\n        file = square & 7\n        rank = square >> 3\n        wf = 7 - file if white_mirror else file\n        bf = 7 - file if black_mirror else file\n        white_owner = 0 if signed_piece > 0 else 1\n        black_owner = 0 if signed_piece < 0 else 1\n        fw = white_bucket * 768 + (white_owner * 6 + plane) * 64 + rank * 8 + wf\n        fb = black_bucket * 768 + (black_owner * 6 + plane) * 64 + (7 - rank) * 8 + bf\n        for lane in range(hidden):\n            scratch[lane] += int(DIRECT_RESIDUAL_FEATURE_WEIGHTS[fw, lane])\n            scratch[hidden + lane] += int(DIRECT_RESIDUAL_FEATURE_WEIGHTS[fb, lane])\n\n    raw = np.int64(0)\n    for lane in range(hidden):\n        white = int(scratch[lane])\n        black = int(scratch[hidden + lane])\n        if white < 0:\n            white = 0\n        elif white > DIRECT_RESIDUAL_QA:\n            white = DIRECT_RESIDUAL_QA\n        if black < 0:\n            black = 0\n        elif black > DIRECT_RESIDUAL_QA:\n            black = DIRECT_RESIDUAL_QA\n        if side == WHITE:\n            us, them = white, black\n        else:\n            us, them = black, white\n        raw += np.int64(us * us) * np.int64(DIRECT_RESIDUAL_OUTPUT_US[lane])\n        raw += np.int64(them * them) * np.int64(DIRECT_RESIDUAL_OUTPUT_THEM[lane])\n\n    cp = trunc_div_scalar(int(raw), DIRECT_RESIDUAL_QA)\n    cp = trunc_div_scalar(cp * DIRECT_RESIDUAL_CP_SCALE, DIRECT_RESIDUAL_QA * DIRECT_RESIDUAL_QB)\n    cp = trunc_div_scalar(cp, DIRECT_RESIDUAL_MODEL_DEN)\n    if DIRECT_RESIDUAL_CAP_CP > 0:\n        if cp > DIRECT_RESIDUAL_CAP_CP:\n            cp = DIRECT_RESIDUAL_CAP_CP\n        elif cp < -DIRECT_RESIDUAL_CAP_CP:\n            cp = -DIRECT_RESIDUAL_CAP_CP\n    return cp\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    s = one(s, anchor, helper, 'helper anchor')

    old = '''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n'''
    new = '''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply]) + _direct_residual_cp(\n                board, side, eval_stack[ply], pseudo_stack[ply]\n            )\n        else:\n'''
    s = one(s, old, new, 'qsearch stand-pat')
    path.write_text(s)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('path', type=Path)
    p.add_argument('--cap-cp', type=int, default=600)
    a = p.parse_args()
    patch(a.path, a.cap_cp)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
