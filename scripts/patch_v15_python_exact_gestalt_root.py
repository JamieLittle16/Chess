#!/usr/bin/env python3
"""Add the exact production Rust Gestalt network as a conservative root-only guardian.

The 1536-wide, nine-bucket network is far too expensive for Python interior search, but root
branching is small.  For each legal root child we compare the exact Gestalt static score with the
current V14 static score, convert that disagreement back to root POV, take one quarter, and cap the
final adjustment at +/-96 cp.  Interior negamax/qsearch remain untouched.

Requires gestalt-b840.nnue beside numba_search.py. Apply after the exact V15 speed stack.
"""
from __future__ import annotations

from pathlib import Path


def one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    s = path.read_text()
    if "EXACT_GESTALT_HIDDEN" in s:
        raise SystemExit("exact Gestalt root guardian already present")

    anchor = "STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n"
    load = '''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# Exact production Rust Gestalt, root-only.  The file is CC0 and its SHA-256 is pinned by the\n# qualification workflow.  Ignore the 62-byte trailing alignment payload after the quantised fields.\n_exact_gestalt_raw = np.fromfile(Path(__file__).with_name("gestalt-b840.nnue"), dtype=np.dtype("<i2"))\nEXACT_GESTALT_HIDDEN = 1536\nEXACT_GESTALT_ROWS = 9 * 768\n_exact_fw_count = EXACT_GESTALT_ROWS * EXACT_GESTALT_HIDDEN\n_exact_bias_start = _exact_fw_count\n_exact_out_start = _exact_bias_start + EXACT_GESTALT_HIDDEN\n_exact_out_bias_index = _exact_out_start + 2 * EXACT_GESTALT_HIDDEN\nif _exact_gestalt_raw.shape[0] < _exact_out_bias_index + 1:\n    raise ValueError("truncated exact Gestalt network")\nEXACT_GESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(\n    _exact_gestalt_raw[:_exact_fw_count].reshape(EXACT_GESTALT_ROWS, EXACT_GESTALT_HIDDEN),\n    dtype=np.int16,\n)\nEXACT_GESTALT_FEATURE_BIAS = np.ascontiguousarray(\n    _exact_gestalt_raw[_exact_bias_start:_exact_out_start], dtype=np.int16\n)\nEXACT_GESTALT_OUTPUT_WEIGHTS = np.ascontiguousarray(\n    _exact_gestalt_raw[_exact_out_start:_exact_out_bias_index], dtype=np.int16\n)\nEXACT_GESTALT_OUTPUT_BIAS = int(_exact_gestalt_raw[_exact_out_bias_index])\ndel _exact_gestalt_raw\nEXACT_GESTALT_QA = 255\nEXACT_GESTALT_QB = 64\nEXACT_GESTALT_SCALE = 400\nEXACT_GESTALT_FINAL_CAP = 96\nEXACT_GESTALT_BUCKET_MAP = np.asarray([\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n], dtype=np.int16)\n'''
    s = one(s, anchor, load, "exact Gestalt model load")

    anchor = '''@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    runtime = '''@njit(cache=False, inline="always")\ndef _exact_gestalt_feature_index(\n    perspective: int, king_square: int, signed_piece: int, square: int\n) -> int:\n    king_file = king_square & 7\n    king_rank = king_square >> 3\n    mapped_king = king_square if perspective == WHITE else (7 - king_rank) * 8 + king_file\n    bucket = int(EXACT_GESTALT_BUCKET_MAP[mapped_king]) % 9\n    file = square & 7\n    rank = square >> 3\n    if king_file >= 4:\n        file = 7 - file\n    if perspective != WHITE:\n        rank = 7 - rank\n    ownership = 0 if signed_piece * perspective > 0 else 1\n    plane = ownership * 6 + abs(signed_piece) - 1\n    return bucket * 768 + plane * 64 + rank * 8 + file\n\n\n@njit(cache=False, inline="never")\ndef _exact_gestalt_cp(board: np.ndarray, side_to_move: int) -> int:\n    white_king = -1\n    black_king = -1\n    for square in range(64):\n        piece = int(board[square])\n        if piece == KING:\n            white_king = square\n        elif piece == -KING:\n            black_king = square\n    if white_king < 0 or black_king < 0:\n        return 0\n\n    raw = np.int64(0)\n    for neuron in range(EXACT_GESTALT_HIDDEN):\n        acc_white = int(EXACT_GESTALT_FEATURE_BIAS[neuron])\n        acc_black = int(EXACT_GESTALT_FEATURE_BIAS[neuron])\n        for square in range(64):\n            piece = int(board[square])\n            if piece == EMPTY:\n                continue\n            fw = _exact_gestalt_feature_index(WHITE, white_king, piece, square)\n            fb = _exact_gestalt_feature_index(-WHITE, black_king, piece, square)\n            acc_white += int(EXACT_GESTALT_FEATURE_WEIGHTS[fw, neuron])\n            acc_black += int(EXACT_GESTALT_FEATURE_WEIGHTS[fb, neuron])\n        if acc_white < 0:\n            acc_white = 0\n        elif acc_white > EXACT_GESTALT_QA:\n            acc_white = EXACT_GESTALT_QA\n        if acc_black < 0:\n            acc_black = 0\n        elif acc_black > EXACT_GESTALT_QA:\n            acc_black = EXACT_GESTALT_QA\n        if side_to_move == WHITE:\n            us = acc_white\n            them = acc_black\n        else:\n            us = acc_black\n            them = acc_white\n        raw += np.int64(us * us) * np.int64(EXACT_GESTALT_OUTPUT_WEIGHTS[neuron])\n        raw += np.int64(them * them) * np.int64(\n            EXACT_GESTALT_OUTPUT_WEIGHTS[EXACT_GESTALT_HIDDEN + neuron]\n        )\n\n    output = trunc_div_scalar(int(raw), EXACT_GESTALT_QA)\n    output += EXACT_GESTALT_OUTPUT_BIAS\n    return trunc_div_scalar(\n        output * EXACT_GESTALT_SCALE, EXACT_GESTALT_QA * EXACT_GESTALT_QB\n    )\n\n\n@njit(cache=False, inline="always")\ndef _root_exact_gestalt_correction(\n    board: np.ndarray, child_side: int, child_eval_state: np.ndarray\n) -> int:\n    teacher_child = _exact_gestalt_cp(board, child_side)\n    current_child = _evaluate_state(child_side, child_eval_state)\n    delta_child = teacher_child - current_child\n    # Convert to root POV, shrink to 25%, then bound the guardian's authority.\n    correction = -trunc_div_scalar(delta_child, 4)\n    if correction > EXACT_GESTALT_FINAL_CAP:\n        correction = EXACT_GESTALT_FINAL_CAP\n    elif correction < -EXACT_GESTALT_FINAL_CAP:\n        correction = -EXACT_GESTALT_FINAL_CAP\n    return correction\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    s = one(s, anchor, runtime, "exact Gestalt runtime")

    root_start = s.index("def _root(")
    root_end = s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful(", root_start)
    root = s[root_start:root_end]
    old = '''        history_contexts[1] = _child_history_context(\n            root_context, root_key, child_halfmove\n        )\n        if index == 0:\n'''
    new = '''        history_contexts[1] = _child_history_context(\n            root_context, root_key, child_halfmove\n        )\n        guardian_correction = _root_exact_gestalt_correction(board, -side, eval_stack[1])\n        search_alpha = alpha - guardian_correction\n        if search_alpha < -INFINITY:\n            search_alpha = -INFINITY\n        elif search_alpha > INFINITY:\n            search_alpha = INFINITY\n        if index == 0:\n'''
    if root.count(old) != 1:
        raise SystemExit(f"root correction insertion anchor count={root.count(old)}")
    root = root.replace(old, new, 1)
    if root.count("                -INFINITY, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,") != 2:
        raise SystemExit("root full-window anchors changed")
    root = root.replace(
        "                -INFINITY, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,",
        "                -INFINITY, -search_alpha, 1, nodes, max_nodes, hard_deadline_ticks,",
    )
    if root.count("                -alpha - 1, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,") != 1:
        raise SystemExit("root scout-window anchor changed")
    root = root.replace(
        "                -alpha - 1, -alpha, 1, nodes, max_nodes, hard_deadline_ticks,",
        "                -search_alpha - 1, -search_alpha, 1, nodes, max_nodes, hard_deadline_ticks,",
        1,
    )
    if root.count("        score = -score\n") != 1:
        raise SystemExit("root score anchor changed")
    root = root.replace("        score = -score\n", "        score = -score + guardian_correction\n", 1)
    s = s[:root_start] + root + s[root_end:]
    path.write_text(s)


def main() -> int:
    import sys
    if len(sys.argv) != 2:
        raise SystemExit("usage: patch_v15_python_exact_gestalt_root.py NUMBA_SEARCH.py")
    patch(Path(sys.argv[1]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
