#!/usr/bin/env python3
"""Add the search-leaf H32 Gestalt student as a root-only learned guardian.

The H32 king-conditioned model was far too expensive as an every-leaf replacement, but its
search-leaf holdout error is dramatically lower than V14 H64.  Root-only use makes that cost tiny.
For every legal root child we compute

    (H32 correction to V13) - (current V14 H64 correction to V13)

from the resulting child position, convert it back to the root side's perspective, and blend that
*difference* into the ordinary searched root score.  Interior search, qsearch and move ordering are
unchanged.  PVS windows are shifted by the move-specific correction, so the modified root objective
is searched consistently rather than only post-hoc re-ranked.

Requires guardian_h32.npz beside numba_search.py. Apply after the exact V15 speed stack.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def one(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path, blend_num: int, blend_den: int) -> None:
    if blend_num <= 0 or blend_den <= 0 or blend_num > blend_den:
        raise SystemExit("blend must satisfy 0 < num <= den")
    s = path.read_text()
    if "GUARDIAN_HIDDEN" in s:
        raise SystemExit("root H32 guardian already present")

    anchor = "STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n"
    load = f'''STUDENT_SCALE_NUM = 1\nSTUDENT_SCALE_DEN = 12\n\n# Root-only search-leaf H32 guardian.  This model is intentionally never evaluated in interior\n# nodes; its richer king-conditioned topology is affordable only because root branching is tiny.\n_guardian_model = np.load(Path(__file__).with_name("guardian_h32.npz"), allow_pickle=False)\nGUARDIAN_FEATURE_WEIGHTS = np.ascontiguousarray(_guardian_model["feature_weights"], dtype=np.int16)\nGUARDIAN_FEATURE_BIAS = np.ascontiguousarray(_guardian_model["feature_bias"], dtype=np.int16)\nGUARDIAN_OUTPUT_US = np.ascontiguousarray(_guardian_model["output_us"], dtype=np.int16)\nGUARDIAN_OUTPUT_THEM = np.ascontiguousarray(_guardian_model["output_them"], dtype=np.int16)\nGUARDIAN_MODEL_DEN = int(np.asarray(_guardian_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])\ndel _guardian_model\nif GUARDIAN_FEATURE_WEIGHTS.shape != (6912, 32):\n    raise ValueError("invalid H32 guardian feature matrix")\nif GUARDIAN_FEATURE_BIAS.shape != (32,) or GUARDIAN_OUTPUT_US.shape != (32,) or GUARDIAN_OUTPUT_THEM.shape != (32,):\n    raise ValueError("invalid H32 guardian head")\nGUARDIAN_HIDDEN = 32\nGUARDIAN_QA = 255\nGUARDIAN_QB = 64\nGUARDIAN_CP_SCALE = 400\nGUARDIAN_BLEND_NUM = {blend_num}\nGUARDIAN_BLEND_DEN = {blend_den}\nGUARDIAN_DELTA_CLAMP = 1200\nGUARDIAN_BUCKET_MAP = np.asarray([\n    0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,\n    7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n    8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,\n], dtype=np.int16)\n'''
    s = one(s, anchor, load, "guardian model load")

    # Insert runtime immediately before the ordinary evaluator helpers.  Nested neuron/square loops
    # avoid heap-allocating temporary accumulator arrays at each root child.
    anchor = '''@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    runtime = '''@njit(cache=False, inline="always")\ndef _guardian_feature_index(\n    perspective: int, king_square: int, signed_piece: int, square: int\n) -> int:\n    king_file = king_square & 7\n    king_rank = king_square >> 3\n    mapped_king = king_square if perspective == WHITE else (7 - king_rank) * 8 + king_file\n    bucket = int(GUARDIAN_BUCKET_MAP[mapped_king]) % 9\n    file = square & 7\n    rank = square >> 3\n    if king_file >= 4:\n        file = 7 - file\n    if perspective != WHITE:\n        rank = 7 - rank\n    ownership = 0 if signed_piece * perspective > 0 else 1\n    plane = ownership * 6 + abs(signed_piece) - 1\n    return bucket * 768 + plane * 64 + rank * 8 + file\n\n\n@njit(cache=False, inline="never")\ndef _guardian_h32_correction_cp(board: np.ndarray, side_to_move: int) -> int:\n    white_king = -1\n    black_king = -1\n    for square in range(64):\n        piece = int(board[square])\n        if piece == KING:\n            white_king = square\n        elif piece == -KING:\n            black_king = square\n    if white_king < 0 or black_king < 0:\n        return 0\n\n    raw = np.int64(0)\n    for neuron in range(GUARDIAN_HIDDEN):\n        acc_white = int(GUARDIAN_FEATURE_BIAS[neuron])\n        acc_black = int(GUARDIAN_FEATURE_BIAS[neuron])\n        for square in range(64):\n            piece = int(board[square])\n            if piece == EMPTY:\n                continue\n            fw = _guardian_feature_index(WHITE, white_king, piece, square)\n            fb = _guardian_feature_index(-WHITE, black_king, piece, square)\n            acc_white += int(GUARDIAN_FEATURE_WEIGHTS[fw, neuron])\n            acc_black += int(GUARDIAN_FEATURE_WEIGHTS[fb, neuron])\n        if acc_white < 0:\n            acc_white = 0\n        elif acc_white > GUARDIAN_QA:\n            acc_white = GUARDIAN_QA\n        if acc_black < 0:\n            acc_black = 0\n        elif acc_black > GUARDIAN_QA:\n            acc_black = GUARDIAN_QA\n        if side_to_move == WHITE:\n            us = acc_white\n            them = acc_black\n        else:\n            us = acc_black\n            them = acc_white\n        raw += np.int64(us * us) * np.int64(GUARDIAN_OUTPUT_US[neuron])\n        raw += np.int64(them * them) * np.int64(GUARDIAN_OUTPUT_THEM[neuron])\n\n    first = trunc_div_scalar(int(raw), GUARDIAN_QA)\n    cp = trunc_div_scalar(first * GUARDIAN_CP_SCALE, GUARDIAN_QA * GUARDIAN_QB)\n    return trunc_div_scalar(cp, GUARDIAN_MODEL_DEN)\n\n\n@njit(cache=False, inline="always")\ndef _root_guardian_correction(\n    board: np.ndarray, child_side: int, child_eval_state: np.ndarray\n) -> int:\n    # Both quantities are corrections to the same V13 base in the child side's perspective.\n    h32 = _guardian_h32_correction_cp(board, child_side)\n    h64 = _evaluate_state(child_side, child_eval_state) - _evaluate_state_v13_only(\n        child_side, child_eval_state\n    )\n    delta_child = h32 - h64\n    if delta_child > GUARDIAN_DELTA_CLAMP:\n        delta_child = GUARDIAN_DELTA_CLAMP\n    elif delta_child < -GUARDIAN_DELTA_CLAMP:\n        delta_child = -GUARDIAN_DELTA_CLAMP\n    # Convert child POV to the mover/root POV before blending.\n    return -trunc_div_scalar(delta_child * GUARDIAN_BLEND_NUM, GUARDIAN_BLEND_DEN)\n\n\n@njit(cache=False, inline="always")\ndef _evaluate_state_classical(side: int, state: np.ndarray) -> int:\n'''
    s = one(s, anchor, runtime, "guardian runtime")

    root_start = s.index("def _root(")
    root_end = s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful(", root_start)
    root = s[root_start:root_end]

    old = '''        history_contexts[1] = _child_history_context(\n            root_context, root_key, child_halfmove\n        )\n        if index == 0:\n'''
    new = '''        history_contexts[1] = _child_history_context(\n            root_context, root_key, child_halfmove\n        )\n        guardian_correction = _root_guardian_correction(board, -side, eval_stack[1])\n        search_alpha = alpha - guardian_correction\n        if search_alpha < -INFINITY:\n            search_alpha = -INFINITY\n        elif search_alpha > INFINITY:\n            search_alpha = INFINITY\n        if index == 0:\n'''
    if root.count(old) != 1:
        raise SystemExit(f"root correction insertion anchor count={root.count(old)}")
    root = root.replace(old, new, 1)

    # Shift the three child windows to search the root objective score = -child + correction.
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
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path)
    p.add_argument("--blend-num", type=int, default=1)
    p.add_argument("--blend-den", type=int, default=2)
    a = p.parse_args()
    patch(a.path, a.blend_num, a.blend_den)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
