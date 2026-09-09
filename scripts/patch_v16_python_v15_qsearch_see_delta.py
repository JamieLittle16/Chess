#!/usr/bin/env python3
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()


def one(old: str, new: str) -> None:
    global s
    n = s.count(old)
    if n != 1:
        raise SystemExit(f"anchor count {n}: {old[:160]!r}")
    s = s.replace(old, new, 1)


one(
    "MAX_QPLY = 10\n",
    """MAX_QPLY = 10
QSEARCH_DELTA_MARGIN = 140
QSEARCH_BAD_CAPTURE_THRESHOLD = -80
QSEARCH_BAD_CAPTURE_ALPHA_MARGIN = 90
QSEARCH_SEE_MAX_EXCHANGES = 24
""",
)

anchor = '''@njit(cache=False)\ndef _quiescence(\n'''
helpers = r'''@njit(cache=False, inline="always")
def _see_capture_is_legal(
    board: np.ndarray,
    side: int,
    source: int,
    target: int,
    white_king: int,
    black_king: int,
) -> bool:
    moving = int(board[source])
    captured = int(board[target])
    result = moving
    if abs(moving) == PAWN:
        target_rank = target >> 3
        if (side == WHITE and target_rank == 7) or (side == -WHITE and target_rank == 0):
            result = side * QUEEN
    board[source] = EMPTY
    board[target] = result
    king = target if abs(moving) == KING else (white_king if side == WHITE else black_king)
    legal = not is_square_attacked(board, king, -side)
    board[source] = moving
    board[target] = captured
    return legal


@njit(cache=False, inline="always")
def _see_ray_attacker(
    board: np.ndarray,
    side: int,
    target: int,
    kind: int,
    white_king: int,
    black_king: int,
    diagonal: bool,
) -> int:
    tf = target & 7
    tr = target >> 3
    for df, dr in ((1, 1), (-1, 1), (1, -1), (-1, -1)) if diagonal else ((1, 0), (-1, 0), (0, 1), (0, -1)):
        f = tf + df
        r = tr + dr
        while 0 <= f < 8 and 0 <= r < 8:
            sq = r * 8 + f
            piece = int(board[sq])
            if piece != EMPTY:
                if piece == side * kind and _see_capture_is_legal(
                    board, side, sq, target, white_king, black_king
                ):
                    return sq
                break
            f += df
            r += dr
    return -1


@njit(cache=False, inline="always")
def _see_find_legal_attacker(
    board: np.ndarray,
    side: int,
    target: int,
    white_king: int,
    black_king: int,
) -> int:
    tf = target & 7
    tr = target >> 3

    sr = tr - 1 if side == WHITE else tr + 1
    if 0 <= sr < 8:
        for sf in (tf - 1, tf + 1):
            if 0 <= sf < 8:
                sq = sr * 8 + sf
                if int(board[sq]) == side * PAWN and _see_capture_is_legal(
                    board, side, sq, target, white_king, black_king
                ):
                    return sq

    for df, dr in ((1, 2), (2, 1), (-1, 2), (-2, 1), (1, -2), (2, -1), (-1, -2), (-2, -1)):
        f = tf + df
        r = tr + dr
        if 0 <= f < 8 and 0 <= r < 8:
            sq = r * 8 + f
            if int(board[sq]) == side * KNIGHT and _see_capture_is_legal(
                board, side, sq, target, white_king, black_king
            ):
                return sq

    sq = _see_ray_attacker(board, side, target, BISHOP, white_king, black_king, True)
    if sq >= 0:
        return sq
    sq = _see_ray_attacker(board, side, target, ROOK, white_king, black_king, False)
    if sq >= 0:
        return sq
    sq = _see_ray_attacker(board, side, target, QUEEN, white_king, black_king, True)
    if sq >= 0:
        return sq
    sq = _see_ray_attacker(board, side, target, QUEEN, white_king, black_king, False)
    if sq >= 0:
        return sq

    for df, dr in ((1, 1), (0, 1), (-1, 1), (1, 0), (-1, 0), (1, -1), (0, -1), (-1, -1)):
        f = tf + df
        r = tr + dr
        if 0 <= f < 8 and 0 <= r < 8:
            sq = r * 8 + f
            if int(board[sq]) == side * KING and _see_capture_is_legal(
                board, side, sq, target, white_king, black_king
            ):
                return sq
    return -1


@njit(cache=False)
def _see_recapture_gain(
    board: np.ndarray,
    side: int,
    target: int,
    white_king: int,
    black_king: int,
    exchange_depth: int,
) -> int:
    if exchange_depth >= QSEARCH_SEE_MAX_EXCHANGES:
        return 0
    source = _see_find_legal_attacker(board, side, target, white_king, black_king)
    if source < 0:
        return 0

    moving = int(board[source])
    captured = int(board[target])
    moving_kind = abs(moving)
    resulting = moving
    promotion_gain = 0
    if moving_kind == PAWN:
        target_rank = target >> 3
        if (side == WHITE and target_rank == 7) or (side == -WHITE and target_rank == 0):
            resulting = side * QUEEN
            promotion_gain = int(PIECE_VALUE[QUEEN]) - int(PIECE_VALUE[PAWN])

    board[source] = EMPTY
    board[target] = resulting
    next_white_king = target if side == WHITE and moving_kind == KING else white_king
    next_black_king = target if side == -WHITE and moving_kind == KING else black_king
    reply = _see_recapture_gain(
        board, -side, target, next_white_king, next_black_king, exchange_depth + 1
    )
    board[source] = moving
    board[target] = captured

    gain = int(PIECE_VALUE[abs(captured)]) + promotion_gain - reply
    return gain if gain > 0 else 0


@njit(cache=False, inline="always")
def _see_after_legal_capture(
    board: np.ndarray,
    side_moved: int,
    move: int,
    captured_piece: int,
    white_king: int,
    black_king: int,
) -> int:
    target = move_to(move)
    promotion = move_promotion(move)
    promotion_gain = (
        int(PIECE_VALUE[promotion]) - int(PIECE_VALUE[PAWN]) if promotion != 0 else 0
    )
    initial_gain = int(PIECE_VALUE[abs(captured_piece)]) + promotion_gain
    reply = _see_recapture_gain(board, -side_moved, target, white_king, black_king, 0)
    return initial_gain - reply


'''
one(anchor, helpers + anchor)
one(
    '''    checked = _state_in_check(board, side, eval_stack[ply])
    if not checked:
''',
    '''    checked = _state_in_check(board, side, eval_stack[ply])
    best_score = -INFINITY
    if not checked:
''',
)
one(
    '''        if stand_pat >= beta:
            return stand_pat, False
        if stand_pat > alpha:
            alpha = stand_pat
''',
    '''        best_score = stand_pat
        if stand_pat >= beta:
            return stand_pat, False
        if stand_pat > alpha:
            alpha = stand_pat
''',
)
one(
    '''    for index in range(count):
        move = int(moves[index])
        packed_order = int(score_stack[ply, index])
        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1
        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
''',
    '''    for index in range(count):
        move = int(moves[index])
        packed_order = int(score_stack[ply, index])
        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1
        target = move_to(move)
        capture = bool(move & FLAG_EP) or int(board[target]) != EMPTY
        promotion = move_promotion(move) != 0
        captured_bound = (
            int(PIECE_VALUE[PAWN])
            if (move & FLAG_EP)
            else int(PIECE_VALUE[abs(int(board[target]))])
        )
        delta_candidate = (
            not checked
            and capture
            and not promotion
            and best_score + captured_bound + QSEARCH_DELTA_MARGIN <= alpha
        )
        bad_capture_candidate = (
            not checked
            and capture
            and not promotion
            and qply > 0
            and best_score + QSEARCH_BAD_CAPTURE_ALPHA_MARGIN <= alpha
        )
        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing
''',
)
one(
    '''        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
''',
    '''        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        if delta_candidate or bad_capture_candidate:
            gives_check = _state_in_check(board, -side, eval_stack[ply + 1])
            if not gives_check:
                prune = delta_candidate
                if not prune and bad_capture_candidate:
                    exchange = _see_after_legal_capture(
                        board,
                        side,
                        move,
                        captured_piece,
                        int(eval_stack[ply + 1][EVAL_WHITE_KING]),
                        int(eval_stack[ply + 1][EVAL_BLACK_KING]),
                    )
                    prune = exchange < QSEARCH_BAD_CAPTURE_THRESHOLD
                if prune:
                    undo_move_inplace(board, side, move, captured_piece, captured_square)
                    continue
        path_keys[ply + 1] = _child_position_key(
''',
)
one(
    '''        score = -score
        if score >= beta:
            return score, False
        if score > alpha:
            alpha = score
''',
    '''        score = -score
        if score > best_score:
            best_score = score
        if score >= beta:
            return score, False
        if score > alpha:
            alpha = score
''',
)

for token in ('QSEARCH_DELTA_MARGIN', '_see_after_legal_capture', 'bad_capture_candidate'):
    if token not in s:
        raise SystemExit(f'missing {token}')
p.write_text(s)
