#!/usr/bin/env python3
"""Blend a small amount of diverse-root Rust-Gestalt H32 knowledge into V14 leaves.

Unlike the rejected full Gestalt replacement, this keeps the qualified V14 evaluator as the search
scale and only nudges qsearch qply-0 stand-pat toward the H32 approximation of production Rust
Gestalt.  This preserves V14's pruning/calibration assumptions while allowing Rust-like strategic
knowledge to shape the tree.

The H32 model is trained as a correction to V13.  Therefore at a leaf we compute:

    v14 = existing qualified V14 score
    rust_like = V13 + H32_Gestalt_correction
    delta = clamp(rust_like - v14, +/- RAW_DELTA_CLAMP)
    blended = v14 + delta * BLEND_NUM / BLEND_DEN

Requires experiments/v15_diverse_gestalt_h32.npz. Apply after the exact V15 speed stack so the V14
H64 state has already been lazily materialised before qsearch entry.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, blend_num: int, blend_den: int, raw_delta_clamp: int) -> None:
    if blend_num <= 0 or blend_den <= 0 or blend_num > blend_den:
        raise SystemExit("blend must satisfy 0 < numerator <= denominator")
    if raw_delta_clamp <= 0:
        raise SystemExit("raw delta clamp must be positive")

    s = path.read_text()
    if "DIVERSE_GESTALT_HIDDEN" in s:
        raise SystemExit("diverse H32 leaf blend already present")

    model_anchor = "STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n"
    model_load = f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# Diverse-root H32 student of the exact production Rust Gestalt evaluator.\n_diverse_gestalt_model = np.load(\n    Path(__file__).with_name("v15_diverse_gestalt_h32.npz"), allow_pickle=False\n)\nDIVERSE_GESTALT_HIDDEN = 32\nDIVERSE_GESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(\n    _diverse_gestalt_model["feature_weights"], dtype=np.int16\n)\nDIVERSE_GESTALT_FEATURE_BIAS = np.ascontiguousarray(\n    _diverse_gestalt_model["feature_bias"], dtype=np.int16\n)\nDIVERSE_GESTALT_OUTPUT_US = np.ascontiguousarray(\n    _diverse_gestalt_model["output_us"], dtype=np.int16\n)\nDIVERSE_GESTALT_OUTPUT_THEM = np.ascontiguousarray(\n    _diverse_gestalt_model["output_them"], dtype=np.int16\n)\nDIVERSE_GESTALT_MODEL_DEN = int(\n    np.asarray(_diverse_gestalt_model["scale_denominator"], dtype=np.int32).reshape(-1)[0]\n)\ndel _diverse_gestalt_model\nif DIVERSE_GESTALT_FEATURE_WEIGHTS.shape != (6912, DIVERSE_GESTALT_HIDDEN):\n    raise ValueError("invalid diverse H32 Gestalt feature matrix")\nif DIVERSE_GESTALT_FEATURE_BIAS.shape != (DIVERSE_GESTALT_HIDDEN,):\n    raise ValueError("invalid diverse H32 Gestalt feature bias")\nif DIVERSE_GESTALT_OUTPUT_US.shape != (DIVERSE_GESTALT_HIDDEN,):\n    raise ValueError("invalid diverse H32 Gestalt us head")\nif DIVERSE_GESTALT_OUTPUT_THEM.shape != (DIVERSE_GESTALT_HIDDEN,):\n    raise ValueError("invalid diverse H32 Gestalt them head")\nif DIVERSE_GESTALT_MODEL_DEN <= 0:\n    raise ValueError("invalid diverse H32 Gestalt scale")\nDIVERSE_GESTALT_QA = 255\nDIVERSE_GESTALT_QB = 64\nDIVERSE_GESTALT_CP_SCALE = 400\nDIVERSE_GESTALT_BLEND_NUM = {blend_num}\nDIVERSE_GESTALT_BLEND_DEN = {blend_den}\nDIVERSE_GESTALT_RAW_DELTA_CLAMP = {raw_delta_clamp}\nDIVERSE_GESTALT_BUCKET_MAP = np.asarray([\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n], dtype=np.int16)\n'''
    s = one(s, model_anchor, model_load, "model load")

    helper_anchor = '''@njit(cache=False, inline="always")\ndef _evaluate_state(side: int, state: np.ndarray) -> int:\n'''
    helpers = '''@njit(cache=False, inline="always")\ndef _diverse_gestalt_feature_index(\n    perspective: int, king_square: int, signed_piece: int, square: int\n) -> int:\n    king_file = king_square & 7\n    king_rank = king_square >> 3\n    map_square = king_square if perspective == WHITE else (7 - king_rank) * 8 + king_file\n    bucket = int(DIVERSE_GESTALT_BUCKET_MAP[map_square]) % 9\n    file = square & 7\n    rank = square >> 3\n    if king_file >= 4:\n        file = 7 - file\n    if perspective != WHITE:\n        rank = 7 - rank\n    ownership = 0 if signed_piece * perspective > 0 else 1\n    plane = ownership * 6 + abs(signed_piece) - 1\n    return bucket * 768 + plane * 64 + rank * 8 + file\n\n\n@njit(cache=False, inline="never")\ndef _diverse_gestalt_h32_correction_cp(\n    board: np.ndarray, side: int, state: np.ndarray\n) -> int:\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    raw = np.int64(0)\n    for neuron in range(DIVERSE_GESTALT_HIDDEN):\n        acc_white = int(DIVERSE_GESTALT_FEATURE_BIAS[neuron])\n        acc_black = int(DIVERSE_GESTALT_FEATURE_BIAS[neuron])\n        for square in range(64):\n            piece = int(board[square])\n            if piece == EMPTY:\n                continue\n            fw = _diverse_gestalt_feature_index(WHITE, white_king, piece, square)\n            fb = _diverse_gestalt_feature_index(-WHITE, black_king, piece, square)\n            acc_white += int(DIVERSE_GESTALT_FEATURE_WEIGHTS[fw, neuron])\n            acc_black += int(DIVERSE_GESTALT_FEATURE_WEIGHTS[fb, neuron])\n        if acc_white < 0:\n            acc_white = 0\n        elif acc_white > DIVERSE_GESTALT_QA:\n            acc_white = DIVERSE_GESTALT_QA\n        if acc_black < 0:\n            acc_black = 0\n        elif acc_black > DIVERSE_GESTALT_QA:\n            acc_black = DIVERSE_GESTALT_QA\n        if side == WHITE:\n            us = acc_white\n            them = acc_black\n        else:\n            us = acc_black\n            them = acc_white\n        raw += np.int64(us * us) * np.int64(DIVERSE_GESTALT_OUTPUT_US[neuron])\n        raw += np.int64(them * them) * np.int64(DIVERSE_GESTALT_OUTPUT_THEM[neuron])\n    scaled = trunc_div_scalar(int(raw), DIVERSE_GESTALT_QA)\n    cp = trunc_div_scalar(\n        scaled * DIVERSE_GESTALT_CP_SCALE,\n        DIVERSE_GESTALT_QA * DIVERSE_GESTALT_QB,\n    )\n    return trunc_div_scalar(cp, DIVERSE_GESTALT_MODEL_DEN)\n\n\n@njit(cache=False, inline="never")\ndef _evaluate_state_diverse_gestalt_blend(\n    board: np.ndarray, side: int, state: np.ndarray\n) -> int:\n    v14 = _evaluate_state(side, state)\n    v13 = _evaluate_state_v13_only(side, state)\n    rust_like = v13 + _diverse_gestalt_h32_correction_cp(board, side, state)\n    delta = rust_like - v14\n    if delta > DIVERSE_GESTALT_RAW_DELTA_CLAMP:\n        delta = DIVERSE_GESTALT_RAW_DELTA_CLAMP\n    elif delta < -DIVERSE_GESTALT_RAW_DELTA_CLAMP:\n        delta = -DIVERSE_GESTALT_RAW_DELTA_CLAMP\n    return v14 + trunc_div_scalar(\n        delta * DIVERSE_GESTALT_BLEND_NUM, DIVERSE_GESTALT_BLEND_DEN\n    )\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state(side: int, state: np.ndarray) -> int:\n'''
    s = one(s, helper_anchor, helpers, "inference helpers")

    q_anchor = '''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n'''
    q_repl = '''        if qply == 0:\n            stand_pat = _evaluate_state_diverse_gestalt_blend(\n                board, side, eval_stack[ply]\n            )\n        else:\n'''
    s = one(s, q_anchor, q_repl, "qsearch qply0 blend")

    path.write_text(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--blend-num", type=int, required=True)
    parser.add_argument("--blend-den", type=int, required=True)
    parser.add_argument("--raw-delta-clamp", type=int, default=800)
    args = parser.parse_args()
    patch(args.path, args.blend_num, args.blend_den, args.raw_delta_clamp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
