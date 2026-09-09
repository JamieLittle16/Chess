#!/usr/bin/env python3
"""Upgrade allocation-free q0 H16 Gestalt to qsearch-local incremental state.

Apply after patch_v15_python_leaf_gestalt_rebuild.py. Ordinary negamax remains V13-prefix only.
The H16 two-perspective state is materialized lazily at the first non-check qsearch node and then
carried incrementally only through the qsearch tactical cone. King moves use a virtual full refresh;
all other qsearch moves update the 32 live lanes by sparse feature deltas.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_leaf_gestalt_qsearch_local.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()
if "LEAF_GESTALT_VALID_OFFSET" in s:
    raise SystemExit("already patched")


def rep(old: str, new: str, n: int = 1, label: str = "") -> None:
    global s
    count = s.count(old)
    if count != n:
        raise SystemExit(f"{label or old[:40]} count={count}, expected={n}")
    s = s.replace(old, new, n)


rep(
    "LEAF_GESTALT_END = LEAF_GESTALT_BLACK_OFFSET + LEAF_GESTALT_HIDDEN\n",
    "LEAF_GESTALT_END = LEAF_GESTALT_BLACK_OFFSET + LEAF_GESTALT_HIDDEN\n"
    "LEAF_GESTALT_VALID_OFFSET = LEAF_GESTALT_END\n",
    label="valid layout",
)

rep(
    '''            black[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[bi, lane])


@njit(cache=False, inline="always")
def _infer_leaf_gestalt_cp''',
    '''            black[lane] += int(LEAF_GESTALT_FEATURE_WEIGHTS[bi, lane])
    state[LEAF_GESTALT_VALID_OFFSET] = 1


@njit(cache=False, inline="always")
def _leaf_gestalt_add_feature(acc: np.ndarray, feature: int, sign: int) -> None:
    for lane in range(LEAF_GESTALT_HIDDEN):
        acc[lane] += sign * int(LEAF_GESTALT_FEATURE_WEIGHTS[feature, lane])


@njit(cache=False, inline="always")
def _virtual_rebuild_leaf_gestalt_after_move(
    board: np.ndarray, side: int, move: int, child: np.ndarray
) -> None:
    white = child[LEAF_GESTALT_WHITE_OFFSET:LEAF_GESTALT_BLACK_OFFSET]
    black = child[LEAF_GESTALT_BLACK_OFFSET:LEAF_GESTALT_END]
    for lane in range(LEAF_GESTALT_HIDDEN):
        bias = int(LEAF_GESTALT_FEATURE_BIAS[lane])
        white[lane] = bias
        black[lane] = bias

    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    moving_signed = int(board[from_square])
    captured_square = to_square
    if move & FLAG_EP:
        captured_square = to_square - 8 * side
    rook_from = -1
    rook_to = -1
    if move & FLAG_CASTLE:
        if to_square == 6:
            rook_from, rook_to = 7, 5
        elif to_square == 2:
            rook_from, rook_to = 0, 3
        elif to_square == 62:
            rook_from, rook_to = 63, 61
        else:
            rook_from, rook_to = 56, 59

    white_king = int(child[EVAL_WHITE_KING])
    black_king = int(child[EVAL_BLACK_KING])
    for square in range(64):
        if square == from_square or square == captured_square or square == rook_from:
            continue
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        wi = _leaf_gestalt_feature_index(WHITE, white_king, signed_piece, square)
        bi = _leaf_gestalt_feature_index(-WHITE, black_king, signed_piece, square)
        _leaf_gestalt_add_feature(white, wi, 1)
        _leaf_gestalt_add_feature(black, bi, 1)

    placed_signed = side * promotion if promotion else moving_signed
    wi = _leaf_gestalt_feature_index(WHITE, white_king, placed_signed, to_square)
    bi = _leaf_gestalt_feature_index(-WHITE, black_king, placed_signed, to_square)
    _leaf_gestalt_add_feature(white, wi, 1)
    _leaf_gestalt_add_feature(black, bi, 1)
    if rook_from >= 0:
        rook_signed = side * ROOK
        wi = _leaf_gestalt_feature_index(WHITE, white_king, rook_signed, rook_to)
        bi = _leaf_gestalt_feature_index(-WHITE, black_king, rook_signed, rook_to)
        _leaf_gestalt_add_feature(white, wi, 1)
        _leaf_gestalt_add_feature(black, bi, 1)
    child[LEAF_GESTALT_VALID_OFFSET] = 1


@njit(cache=False, inline="always")
def _advance_leaf_gestalt_q_into(
    board: np.ndarray, side: int, move: int, parent: np.ndarray, child: np.ndarray
) -> None:
    if int(parent[LEAF_GESTALT_VALID_OFFSET]) == 0:
        child[LEAF_GESTALT_VALID_OFFSET] = 0
        return
    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    moving_signed = int(board[from_square])
    if abs(moving_signed) == KING:
        # A king move can change bucket or horizontal mirroring. Rebuild the tiny H16 state
        # virtually from the pre-move board; king moves are rare in tactical qsearch.
        _virtual_rebuild_leaf_gestalt_after_move(board, side, move, child)
        return

    for lane in range(LEAF_GESTALT_HIDDEN):
        child[LEAF_GESTALT_WHITE_OFFSET + lane] = parent[LEAF_GESTALT_WHITE_OFFSET + lane]
        child[LEAF_GESTALT_BLACK_OFFSET + lane] = parent[LEAF_GESTALT_BLACK_OFFSET + lane]

    white_king = int(parent[EVAL_WHITE_KING])
    black_king = int(parent[EVAL_BLACK_KING])
    white = child[LEAF_GESTALT_WHITE_OFFSET:LEAF_GESTALT_BLACK_OFFSET]
    black = child[LEAF_GESTALT_BLACK_OFFSET:LEAF_GESTALT_END]

    wi = _leaf_gestalt_feature_index(WHITE, white_king, moving_signed, from_square)
    bi = _leaf_gestalt_feature_index(-WHITE, black_king, moving_signed, from_square)
    _leaf_gestalt_add_feature(white, wi, -1)
    _leaf_gestalt_add_feature(black, bi, -1)

    captured_square = to_square
    captured_signed = int(board[to_square])
    if move & FLAG_EP:
        captured_square = to_square - 8 * side
        captured_signed = int(board[captured_square])
    if captured_signed != EMPTY:
        wi = _leaf_gestalt_feature_index(WHITE, white_king, captured_signed, captured_square)
        bi = _leaf_gestalt_feature_index(-WHITE, black_king, captured_signed, captured_square)
        _leaf_gestalt_add_feature(white, wi, -1)
        _leaf_gestalt_add_feature(black, bi, -1)

    placed_signed = side * promotion if promotion else moving_signed
    wi = _leaf_gestalt_feature_index(WHITE, white_king, placed_signed, to_square)
    bi = _leaf_gestalt_feature_index(-WHITE, black_king, placed_signed, to_square)
    _leaf_gestalt_add_feature(white, wi, 1)
    _leaf_gestalt_add_feature(black, bi, 1)
    child[LEAF_GESTALT_VALID_OFFSET] = 1


@njit(cache=False, inline="always")
def _infer_leaf_gestalt_cp''',
    label="qsearch local helpers",
)

rep(
    '''    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
        if qply == 0:
            _build_leaf_gestalt_into(board, eval_stack[ply])
            stand_pat = _evaluate_state_leaf_gestalt(side, eval_stack[ply])
        else:
            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])
''',
    '''    if qply == 0:
        # Rows are reused across branches, so reset validity at each ordinary qsearch entry.
        eval_stack[ply][LEAF_GESTALT_VALID_OFFSET] = 0
    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
        if int(eval_stack[ply][LEAF_GESTALT_VALID_OFFSET]) == 0:
            _build_leaf_gestalt_into(board, eval_stack[ply])
        stand_pat = _evaluate_state_leaf_gestalt(side, eval_stack[ply])
''',
    label="all qsearch standpat",
)

rep(
    '''        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
''',
    '''        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        _advance_leaf_gestalt_q_into(
            board, side, move, eval_stack[ply], eval_stack[ply + 1]
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
''',
    label="qsearch transport",
)

p.write_text(s)
