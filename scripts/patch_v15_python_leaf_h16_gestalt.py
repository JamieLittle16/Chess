#!/usr/bin/env python3
"""Replace V14's absolute H64 residual with a leaf-materialized H16 Rust-Gestalt student.

The H16 student was distilled on real Rust Gestalt search leaves.  It has 16 hidden lanes per
perspective (32 live lanes total) and predicts the Rust-Gestalt correction relative to the exact V13
prefix.  Ordinary negamax therefore carries only the eight-cell V13 state.  The richer king-bucket
student is reconstructed only at qply==0 stand-pat (and emergency root fallback), reusing the eval
stack tail instead of allocating or maintaining a second accumulator through every searched edge.

Apply after the one-pass presort and score-metadata patches.  ``--runtime-den`` permits a conservative
fractional deployment during qualification: 1 is the exact trained student, 2 is half strength.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_exact(source: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    return source.replace(old, new, expected)


def patch(path: Path, runtime_den: int) -> None:
    if runtime_den <= 0:
        raise SystemExit("runtime denominator must be positive")
    s = path.read_text()

    s = replace_exact(
        s,
        '''from experiments.v14_student_single_runtime import (\n    advance_absolute768_accumulator_into,\n    build_absolute768_accumulator_into,\n    infer_absolute768_student_cp,\n    trunc_div_scalar,\n)\n''',
        '''from experiments.v14_student_single_runtime import trunc_div_scalar\n''',
        "V14 student import",
    )

    s = replace_exact(
        s,
        '''_student_model = np.load(Path(__file__).with_name("v14_student_h64.npz"), allow_pickle=False)\nSTUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)\nSTUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)\nSTUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)\nSTUDENT_OUTPUT_BIAS = int(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1)[0])\ndel _student_model\nif STUDENT_FEATURE_WEIGHTS.shape != (768, 64):\n    raise ValueError("invalid V14 H64 student feature matrix")\nif STUDENT_FEATURE_BIAS.shape != (64,) or STUDENT_OUTPUT_WEIGHTS.shape != (64,):\n    raise ValueError("invalid V14 H64 student head")\nSTUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n''',
        f'''_gestalt_model = np.load(Path(__file__).with_name("v15_gestalt_h16.npz"), allow_pickle=False)\nGESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(_gestalt_model["feature_weights"], dtype=np.int16)\nGESTALT_FEATURE_BIAS = np.ascontiguousarray(_gestalt_model["feature_bias"], dtype=np.int16)\nGESTALT_OUTPUT_US = np.ascontiguousarray(_gestalt_model["output_us"], dtype=np.int16)\nGESTALT_OUTPUT_THEM = np.ascontiguousarray(_gestalt_model["output_them"], dtype=np.int16)\nGESTALT_SCALE_DEN = int(np.asarray(_gestalt_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _gestalt_model\nGESTALT_HIDDEN = 16\nGESTALT_QA = 255\nGESTALT_QB = 64\nGESTALT_CP_SCALE = 400\nGESTALT_RUNTIME_DEN = {runtime_den}\nif GESTALT_FEATURE_WEIGHTS.shape != (6912, GESTALT_HIDDEN):\n    raise ValueError("invalid V15 H16 Gestalt feature matrix")\nif GESTALT_FEATURE_BIAS.shape != (GESTALT_HIDDEN,):\n    raise ValueError("invalid V15 H16 Gestalt feature bias")\nif GESTALT_OUTPUT_US.shape != (GESTALT_HIDDEN,) or GESTALT_OUTPUT_THEM.shape != (GESTALT_HIDDEN,):\n    raise ValueError("invalid V15 H16 Gestalt output head")\nif GESTALT_SCALE_DEN <= 0 or GESTALT_RUNTIME_DEN <= 0:\n    raise ValueError("invalid V15 H16 Gestalt scale denominator")\nGESTALT_BUCKET_MAP = np.asarray((\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n), dtype=np.int16)\n''',
        "student model",
    )

    s = replace_exact(
        s,
        '''STUDENT_OFFSET = EVAL_V13_WIDTH\nSTUDENT_HIDDEN = 64\nEVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN\n''',
        '''STUDENT_OFFSET = EVAL_V13_WIDTH\nGESTALT_WHITE_OFFSET = STUDENT_OFFSET\nGESTALT_BLACK_OFFSET = GESTALT_WHITE_OFFSET + GESTALT_HIDDEN\nEVAL_WIDTH = GESTALT_BLACK_OFFSET + GESTALT_HIDDEN\n''',
        "eval layout",
    )

    s = replace_exact(
        s,
        '''    build_absolute768_accumulator_into(\n        board,\n        STUDENT_FEATURE_WEIGHTS,\n        STUDENT_FEATURE_BIAS,\n        state[STUDENT_OFFSET:EVAL_WIDTH],\n    )\n''',
        '''    # Rich student is leaf-materialized; ordinary search carries only the V13 prefix.\n''',
        "root student build",
    )

    start = s.index('@njit(cache=False, inline="always")\ndef _evaluate_state(side: int, state: np.ndarray) -> int:\n')
    end = s.index('\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_v13_only', start)
    s = s[:start] + '''@njit(cache=False, inline="always")\ndef _evaluate_state(side: int, state: np.ndarray) -> int:\n    # Compatibility fallback: all normal V15 leaf evaluation has board access below.\n    score = _evaluate_state_classical(side, state)\n    if side == WHITE:\n        correction = int(state[EVAL_RESIDUAL_WHITE]) - int(state[EVAL_RESIDUAL_BLACK])\n    else:\n        correction = int(state[EVAL_RESIDUAL_BLACK]) - int(state[EVAL_RESIDUAL_WHITE])\n    correction += RESIDUAL_BIAS\n    if RESIDUAL_CLAMP > 0:\n        if correction > RESIDUAL_CLAMP:\n            correction = RESIDUAL_CLAMP\n        elif correction < -RESIDUAL_CLAMP:\n            correction = -RESIDUAL_CLAMP\n    return score + correction // 6\n''' + s[end:]

    anchor = '''@njit(cache=False, inline="never")\ndef _advance_residual_state_into(\n'''
    helper = '''@njit(cache=False, inline="always")\ndef _gestalt_bucket_for_king(king_square: int, perspective: int) -> int:\n    mapped = king_square\n    if perspective != WHITE:\n        mapped = (king_square & 7) + (7 - (king_square >> 3)) * 8\n    return int(GESTALT_BUCKET_MAP[mapped]) % 9\n\n\n@njit(cache=False, inline="never")\ndef _evaluate_gestalt_leaf(board: np.ndarray, side: int, state: np.ndarray) -> int:\n    white = state[GESTALT_WHITE_OFFSET:GESTALT_BLACK_OFFSET]\n    black = state[GESTALT_BLACK_OFFSET:EVAL_WIDTH]\n    for lane in range(GESTALT_HIDDEN):\n        bias = int(GESTALT_FEATURE_BIAS[lane])\n        white[lane] = bias\n        black[lane] = bias\n\n    white_king = int(state[EVAL_WHITE_KING])\n    black_king = int(state[EVAL_BLACK_KING])\n    white_bucket = _gestalt_bucket_for_king(white_king, WHITE)\n    black_bucket = _gestalt_bucket_for_king(black_king, -WHITE)\n    white_mirror = (white_king & 7) >= 4\n    black_mirror = (black_king & 7) >= 4\n\n    for square in range(64):\n        signed_piece = int(board[square])\n        if signed_piece == EMPTY:\n            continue\n        piece_plane = abs(signed_piece) - 1\n        file = square & 7\n        rank = square >> 3\n\n        white_file = 7 - file if white_mirror else file\n        white_owner = 0 if signed_piece > 0 else 1\n        white_feature = (\n            white_bucket * 768 + (white_owner * 6 + piece_plane) * 64 + rank * 8 + white_file\n        )\n\n        black_file = 7 - file if black_mirror else file\n        black_rank = 7 - rank\n        black_owner = 0 if signed_piece < 0 else 1\n        black_feature = (\n            black_bucket * 768 + (black_owner * 6 + piece_plane) * 64 + black_rank * 8 + black_file\n        )\n\n        for lane in range(GESTALT_HIDDEN):\n            white[lane] += int(GESTALT_FEATURE_WEIGHTS[white_feature, lane])\n            black[lane] += int(GESTALT_FEATURE_WEIGHTS[black_feature, lane])\n\n    raw = np.int64(0)\n    for lane in range(GESTALT_HIDDEN):\n        white_value = int(white[lane])\n        black_value = int(black[lane])\n        if white_value < 0:\n            white_value = 0\n        elif white_value > GESTALT_QA:\n            white_value = GESTALT_QA\n        if black_value < 0:\n            black_value = 0\n        elif black_value > GESTALT_QA:\n            black_value = GESTALT_QA\n        if side == WHITE:\n            us_value = white_value\n            them_value = black_value\n        else:\n            us_value = black_value\n            them_value = white_value\n        raw += (\n            np.int64(us_value * us_value) * np.int64(GESTALT_OUTPUT_US[lane])\n            + np.int64(them_value * them_value) * np.int64(GESTALT_OUTPUT_THEM[lane])\n        )\n\n    correction_cp = trunc_div_scalar(raw, GESTALT_QA)\n    correction_cp = trunc_div_scalar(\n        correction_cp * GESTALT_CP_SCALE, GESTALT_QA * GESTALT_QB\n    )\n    correction_cp = trunc_div_scalar(correction_cp, GESTALT_SCALE_DEN * GESTALT_RUNTIME_DEN)\n    return _evaluate_state_v13_only(side, state) + correction_cp\n\n\n@njit(cache=False, inline="never")\ndef _advance_residual_state_into(\n'''
    s = replace_exact(s, anchor, helper, "Gestalt helper anchor")

    s = replace_exact(
        s,
        '''    _advance_residual_state_into(board, side, move, parent, child)\n    advance_absolute768_accumulator_into(\n        board,\n        side,\n        move,\n        parent[STUDENT_OFFSET:EVAL_WIDTH],\n        child[STUDENT_OFFSET:EVAL_WIDTH],\n        STUDENT_FEATURE_WEIGHTS,\n    )\n''',
        '''    _advance_residual_state_into(board, side, move, parent, child)\n    # No student transport: Gestalt is reconstructed only at an evaluable leaf.\n''',
        "student transport",
    )

    s = replace_exact(
        s,
        '''        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n''',
        '''        if qply == 0:\n            stand_pat = _evaluate_gestalt_leaf(board, side, eval_stack[ply])\n        else:\n''',
        "qsearch leaf evaluation",
    )

    fallback = 'fallback_score = -_evaluate_state(-side, eval_stack[1])'
    if s.count(fallback) != 3:
        raise SystemExit(f"fallback evaluation: expected 3, found {s.count(fallback)}")
    s = s.replace(
        fallback,
        'fallback_score = -_evaluate_gestalt_leaf(board, -side, eval_stack[1])',
    )

    if "STUDENT_FEATURE_WEIGHTS" in s or "advance_absolute768_accumulator_into" in s:
        raise SystemExit("legacy H64 search transport remains after Gestalt patch")
    path.write_text(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--runtime-den", type=int, default=1)
    args = parser.parse_args()
    patch(args.path, args.runtime_den)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
