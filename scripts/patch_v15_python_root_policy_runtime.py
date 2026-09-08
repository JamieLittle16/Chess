#!/usr/bin/env python3
"""Add the distilled H64 policy as a shallow root-ordering seed.

The policy is deliberately conservative: it is evaluated only at root depth 1, where its top-k
moves are rotated ahead of V14's otherwise unchanged stable order. Later iterative-deepening
iterations use the engine's own previous best move as usual, so the student can seed search but can
never bypass verification or keep overriding deeper evidence.
"""
from __future__ import annotations

from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_root_policy_runtime.py SEARCH.py TOP_K")
p=Path(sys.argv[1]); top_k=int(sys.argv[2])
if top_k not in (1,3): raise SystemExit("TOP_K must be 1 or 3")
s=p.read_text()


def rep(old,new,n=1,label=""):
    global s
    c=s.count(old)
    if c!=n: raise SystemExit(f"{label or old[:40]} count={c} expected={n}")
    s=s.replace(old,new,n)

anchor='''del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
'''
insert='''del _student_model

_policy_model = np.load(Path(__file__).with_name("v15_root_policy.npz"), allow_pickle=False)
POLICY_BOARD_W = np.ascontiguousarray(_policy_model["board_w"], dtype=np.float32)
POLICY_BOARD_B = np.ascontiguousarray(_policy_model["board_b"], dtype=np.float32)
POLICY_MOVE_W = np.ascontiguousarray(_policy_model["move_w"], dtype=np.float32)
POLICY_MOVE_B = np.ascontiguousarray(_policy_model["move_b"], dtype=np.float32)
POLICY_HEAD_W = np.ascontiguousarray(_policy_model["head_w"], dtype=np.float32)
POLICY_HEAD_B = np.ascontiguousarray(_policy_model["head_b"], dtype=np.float32)
POLICY_OUT_W = np.ascontiguousarray(_policy_model["out_w"], dtype=np.float32)
POLICY_OUT_B = float(np.asarray(_policy_model["out_b"], dtype=np.float32).reshape(-1)[0])
del _policy_model
if POLICY_BOARD_W.shape != (64, 773) or POLICY_MOVE_W.shape != (64, 149):
    raise ValueError("invalid V15 root policy first layers")
if POLICY_HEAD_W.shape != (64, 128) or POLICY_OUT_W.shape != (64,):
    raise ValueError("invalid V15 root policy head")
POLICY_TOP_K = %d

if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
''' % top_k
rep(anchor,insert,label="policy load")

old='''    BISHOP,
    EMPTY,
    FLAG_CASTLE,
'''
new='''    BISHOP,
    CASTLE_BK,
    CASTLE_BQ,
    CASTLE_WK,
    CASTLE_WQ,
    EMPTY,
    FLAG_CASTLE,
'''
rep(old,new,label="castling imports")

marker='''@njit(cache=False)
def _order_moves(
'''
helpers='''@njit(cache=False, inline="always")
def _policy_board_feature_plane(signed_piece: int) -> int:
    return (0 if signed_piece > 0 else 6) + abs(signed_piece) - 1


@njit(cache=False)
def _policy_board_hidden(board: np.ndarray, side: int, castling: int, out: np.ndarray) -> None:
    for h in range(64):
        value = float(POLICY_BOARD_B[h])
        for square in range(64):
            piece = int(board[square])
            if piece != 0:
                feature = _policy_board_feature_plane(piece) * 64 + square
                value += float(POLICY_BOARD_W[h, feature])
        value += float(POLICY_BOARD_W[h, 768]) * (1.0 if side == WHITE else -1.0)
        if castling & CASTLE_WK: value += float(POLICY_BOARD_W[h, 769])
        if castling & CASTLE_WQ: value += float(POLICY_BOARD_W[h, 770])
        if castling & CASTLE_BK: value += float(POLICY_BOARD_W[h, 771])
        if castling & CASTLE_BQ: value += float(POLICY_BOARD_W[h, 772])
        out[h] = value if value > 0.0 else 0.0


@njit(cache=False)
def _policy_move_logit(
    board: np.ndarray,
    move: int,
    board_hidden: np.ndarray,
    move_hidden: np.ndarray,
    head_hidden: np.ndarray,
) -> float:
    from_square = move_from(move)
    to_square = move_to(move)
    moving = abs(int(board[from_square]))
    captured = PAWN if (move & FLAG_EP) else abs(int(board[to_square]))
    promotion = move_promotion(move)
    for h in range(64):
        value = float(POLICY_MOVE_B[h])
        value += float(POLICY_MOVE_W[h, from_square])
        value += float(POLICY_MOVE_W[h, 64 + to_square])
        if moving: value += float(POLICY_MOVE_W[h, 128 + moving - 1])
        if captured: value += float(POLICY_MOVE_W[h, 134 + captured - 1])
        if promotion: value += float(POLICY_MOVE_W[h, 140 + promotion - 1])
        if captured or (move & FLAG_EP): value += float(POLICY_MOVE_W[h, 145])
        # Feature 146 (gives-check) was zeroed during runtime-exact training.
        if move & FLAG_CASTLE: value += float(POLICY_MOVE_W[h, 147])
        if move & FLAG_EP: value += float(POLICY_MOVE_W[h, 148])
        move_hidden[h] = value if value > 0.0 else 0.0
    for h in range(64):
        value = float(POLICY_HEAD_B[h])
        for j in range(64):
            value += float(POLICY_HEAD_W[h, j]) * float(board_hidden[j])
            value += float(POLICY_HEAD_W[h, 64 + j]) * float(move_hidden[j])
        head_hidden[h] = value if value > 0.0 else 0.0
    score = POLICY_OUT_B
    for h in range(64):
        score += float(POLICY_OUT_W[h]) * float(head_hidden[h])
    return score


@njit(cache=False)
def _promote_policy_top_k(
    board: np.ndarray,
    side: int,
    castling: int,
    moves: np.ndarray,
    scores: np.ndarray,
    count: int,
) -> None:
    if count <= 1:
        return
    board_hidden = np.empty(64, dtype=np.float32)
    move_hidden = np.empty(64, dtype=np.float32)
    head_hidden = np.empty(64, dtype=np.float32)
    policy_scores = np.empty(MAX_MOVES, dtype=np.float32)
    _policy_board_hidden(board, side, castling, board_hidden)
    for i in range(count):
        policy_scores[i] = _policy_move_logit(
            board, int(moves[i]), board_hidden, move_hidden, head_hidden
        )
    limit = min(POLICY_TOP_K, count)
    for index in range(limit):
        best = index
        best_score = float(policy_scores[index])
        for candidate in range(index + 1, count):
            value = float(policy_scores[candidate])
            if value > best_score:
                best = candidate
                best_score = value
        if best == index:
            continue
        best_move = int(moves[best])
        best_base_score = int(scores[best])
        best_policy = float(policy_scores[best])
        cursor = best
        while cursor > index:
            moves[cursor] = moves[cursor - 1]
            scores[cursor] = scores[cursor - 1]
            policy_scores[cursor] = policy_scores[cursor - 1]
            cursor -= 1
        moves[index] = best_move
        scores[index] = best_base_score
        policy_scores[index] = best_policy


@njit(cache=False)
def _order_moves(
'''
rep(marker,helpers,label="policy helpers")

old='''    _order_moves(board, moves, count, preferred, score_stack[0])

    best_move = int(moves[0])
'''
new='''    _order_moves(board, moves, count, preferred, score_stack[0])
    # Seed only the first completed iteration. Deeper iterations retain the engine's own PV move.
    if depth == 1:
        _promote_policy_top_k(board, side, castling, moves, score_stack[0], count)

    best_move = int(moves[0])
'''
rep(old,new,label="root policy call")

p.write_text(s)
