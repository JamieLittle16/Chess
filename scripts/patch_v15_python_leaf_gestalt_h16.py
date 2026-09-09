#!/usr/bin/env python3
"""Replace V14's always-carried H64 leaf term with a leaf-only H16 Gestalt student.

The student was distilled from the exact production Rust Gestalt network on positions observed at the
real Rust Searcher::leaf_evaluate boundary. It keeps Gestalt's nine king buckets and separate
White/Black perspective heads, but is rebuilt from the current board only when qsearch actually
needs a qply-0 stand-pat. Ordinary interior search therefore carries only the exact V13 eight-cell
evaluation prefix; the V14 H64 tail is neither built nor advanced.

Apply after the one-pass presort patch to an exact packaged V14 tree. Copy the trained model to
experiments/v15_leaf_gestalt_h16.npz before importing the patched engine.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_leaf_gestalt_h16.py SEARCH.py")

p = Path(sys.argv[1])
s = p.read_text()


def rep(old: str, new: str, n: int = 1, label: str = "") -> None:
    global s
    count = s.count(old)
    if count != n:
        raise SystemExit(f"{label or old[:40]!r}: count={count} expected={n}")
    s = s.replace(old, new, n)


anchor = """STUDENT_SCALE_NUM = 1
STUDENT_SCALE_DEN = 12
"""
model = """STUDENT_SCALE_NUM = 1
STUDENT_SCALE_DEN = 12

_leaf_gestalt_model = np.load(
    Path(__file__).with_name("v15_leaf_gestalt_h16.npz"), allow_pickle=False
)
LEAF_GESTALT_HIDDEN = 16
LEAF_GESTALT_FEATURE_WEIGHTS = np.ascontiguousarray(
    _leaf_gestalt_model["feature_weights"], dtype=np.int16
)
LEAF_GESTALT_FEATURE_BIAS = np.ascontiguousarray(
    _leaf_gestalt_model["feature_bias"], dtype=np.int16
)
LEAF_GESTALT_OUTPUT_US = np.ascontiguousarray(
    _leaf_gestalt_model["output_us"], dtype=np.int16
)
LEAF_GESTALT_OUTPUT_THEM = np.ascontiguousarray(
    _leaf_gestalt_model["output_them"], dtype=np.int16
)
LEAF_GESTALT_SCALE_DEN = int(
    np.asarray(_leaf_gestalt_model["scale_denominator"], dtype=np.int32).reshape(-1)[0]
)
del _leaf_gestalt_model
if LEAF_GESTALT_FEATURE_WEIGHTS.shape != (6912, LEAF_GESTALT_HIDDEN):
    raise ValueError("invalid V15 leaf Gestalt H16 feature matrix")
if LEAF_GESTALT_FEATURE_BIAS.shape != (LEAF_GESTALT_HIDDEN,):
    raise ValueError("invalid V15 leaf Gestalt H16 feature bias")
if LEAF_GESTALT_OUTPUT_US.shape != (LEAF_GESTALT_HIDDEN,):
    raise ValueError("invalid V15 leaf Gestalt H16 us head")
if LEAF_GESTALT_OUTPUT_THEM.shape != (LEAF_GESTALT_HIDDEN,):
    raise ValueError("invalid V15 leaf Gestalt H16 them head")
if LEAF_GESTALT_SCALE_DEN <= 0:
    raise ValueError("invalid V15 leaf Gestalt H16 scale")
LEAF_GESTALT_QA = 255
LEAF_GESTALT_QB = 64
LEAF_GESTALT_CP_SCALE = 400
LEAF_GESTALT_BUCKET_MAP = np.asarray(
    [
        0, 1, 2, 3, 12, 11, 10, 9,
        4, 4, 5, 5, 14, 14, 13, 13,
        6, 6, 6, 6, 15, 15, 15, 15,
        7, 7, 7, 7, 16, 16, 16, 16,
        8, 8, 8, 8, 17, 17, 17, 17,
        8, 8, 8, 8, 17, 17, 17, 17,
        8, 8, 8, 8, 17, 17, 17, 17,
        8, 8, 8, 8, 17, 17, 17, 17,
    ],
    dtype=np.int16,
)
"""
rep(anchor, model, label="leaf model load")

old_build = """    build_absolute768_accumulator_into(
        board,
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:EVAL_WIDTH],
    )
"""
rep(old_build, "", label="disable root H64 build")

anchor = '''@njit(cache=False, inline="always")
def _evaluate_state(side: int, state: np.ndarray) -> int:
'''
helpers = '''@njit(cache=False, inline="always")
def _leaf_gestalt_feature_index(
    perspective: int,
    king_square: int,
    signed_piece: int,
    square: int,
) -> int:
    map_square = king_square
    if perspective != WHITE:
        map_square = (7 - (king_square >> 3)) * 8 + (king_square & 7)
    raw_bucket = int(LEAF_GESTALT_BUCKET_MAP[map_square])
    bucket = raw_bucket % 9
    mirror_files = (king_square & 7) >= 4

    file = square & 7
    rank = square >> 3
    if mirror_files:
        file = 7 - file
    if perspective != WHITE:
        rank = 7 - rank

    same_owner = (signed_piece > 0) == (perspective == WHITE)
    ownership = 0 if same_owner else 1
    plane = ownership * 6 + (abs(signed_piece) - 1)
    return bucket * 768 + plane * 64 + rank * 8 + file


@njit(cache=False)
def _leaf_gestalt_correction_cp(board: np.ndarray, side: int, state: np.ndarray) -> int:
    """Return the distilled Gestalt residual in side-to-move coordinates."""
    white_king = int(state[EVAL_WHITE_KING])
    black_king = int(state[EVAL_BLACK_KING])
    white_acc = np.empty(LEAF_GESTALT_HIDDEN, dtype=np.int32)
    black_acc = np.empty(LEAF_GESTALT_HIDDEN, dtype=np.int32)
    for lane in range(LEAF_GESTALT_HIDDEN):
        bias = int(LEAF_GESTALT_FEATURE_BIAS[lane])
        white_acc[lane] = bias
        black_acc[lane] = bias

    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        white_feature = _leaf_gestalt_feature_index(
            WHITE, white_king, signed_piece, square
        )
        black_feature = _leaf_gestalt_feature_index(
            -WHITE, black_king, signed_piece, square
        )
        for lane in range(LEAF_GESTALT_HIDDEN):
            white_acc[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[white_feature, lane])
            black_acc[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[black_feature, lane])

    raw = np.int64(0)
    for lane in range(LEAF_GESTALT_HIDDEN):
        if side == WHITE:
            us = int(white_acc[lane])
            them = int(black_acc[lane])
        else:
            us = int(black_acc[lane])
            them = int(white_acc[lane])
        if us < 0:
            us = 0
        elif us > LEAF_GESTALT_QA:
            us = LEAF_GESTALT_QA
        if them < 0:
            them = 0
        elif them > LEAF_GESTALT_QA:
            them = LEAF_GESTALT_QA
        raw += (
            np.int64(us * us) * np.int64(LEAF_GESTALT_OUTPUT_US[lane])
            + np.int64(them * them) * np.int64(LEAF_GESTALT_OUTPUT_THEM[lane])
        )

    scaled = trunc_div_scalar(raw, LEAF_GESTALT_QA)
    cp = trunc_div_scalar(
        scaled * LEAF_GESTALT_CP_SCALE,
        LEAF_GESTALT_QA * LEAF_GESTALT_QB,
    )
    return trunc_div_scalar(cp, LEAF_GESTALT_SCALE_DEN)


@njit(cache=False)
def _evaluate_state_leaf_gestalt(
    board: np.ndarray,
    side: int,
    state: np.ndarray,
) -> int:
    return _evaluate_state_v13_only(side, state) + _leaf_gestalt_correction_cp(
        board, side, state
    )


@njit(cache=False, inline="always")
def _evaluate_state(side: int, state: np.ndarray) -> int:
'''
rep(anchor, helpers, label="leaf inference helpers")

rep(
    """        if qply == 0:
            stand_pat = _evaluate_state(side, eval_stack[ply])
        else:
""",
    """        if qply == 0:
            stand_pat = _evaluate_state_leaf_gestalt(board, side, eval_stack[ply])
        else:
""",
    label="qsearch qply0 evaluator",
)

rep(
    "fallback_score = -_evaluate_state(-side, eval_stack[1])",
    "fallback_score = -_evaluate_state_leaf_gestalt(board, -side, eval_stack[1])",
    n=3,
    label="fallback evaluator",
)

rep(
    "_advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])",
    "_advance_eval_state_into(\n            board, side, move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )",
    label="interior V13-only transport",
)
rep(
    "_advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])",
    "_advance_eval_state_into(\n            board, side, move,\n            eval_stack[0, :EVAL_V13_WIDTH],\n            eval_stack[1, :EVAL_V13_WIDTH],\n        )",
    n=4,
    label="root/fallback V13-only transport",
)

if s.count("stand_pat = _evaluate_state(side, eval_stack[ply])"):
    raise SystemExit("old qply0 evaluator remains")
if s.count("fallback_score = -_evaluate_state(-side, eval_stack[1])"):
    raise SystemExit("old fallback evaluator remains")
if s.count("_advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])"):
    raise SystemExit("full root H64 transport remains")
if s.count("_advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])"):
    raise SystemExit("full interior H64 transport remains")

p.write_text(s)
