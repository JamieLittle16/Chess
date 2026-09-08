#!/usr/bin/env python3
"""Add a tiny Numba-native root policy as ordering-only guidance.

The policy never chooses a move directly. It scores the already-legal root list, keeps the previous
PV/TT move first, and stably orders the remaining candidates before ordinary PVS verification.
`blend_divisor` controls how much of V14's tactical/center ordering remains in the policy score:
0 = pure policy, 4/8/16 = add base_order/divisor.
"""
from pathlib import Path
import argparse

ap=argparse.ArgumentParser();ap.add_argument('search',type=Path);ap.add_argument('--blend-divisor',type=int,default=8);a=ap.parse_args()
if a.blend_divisor not in (0,4,8,16): raise SystemExit('blend divisor must be 0,4,8,16')
p=a.search;s=p.read_text()

anchor='''STUDENT_SCALE_NUM = 1
STUDENT_SCALE_DEN = 12
'''
insert=f'''STUDENT_SCALE_NUM = 1
STUDENT_SCALE_DEN = 12

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
    raise ValueError("invalid V15 root policy input matrices")
if POLICY_HEAD_W.shape != (64, 128) or POLICY_OUT_W.shape != (64,):
    raise ValueError("invalid V15 root policy head")
POLICY_BLEND_DIVISOR = {a.blend_divisor}
POLICY_LOGIT_SCALE = 1_000_000.0
'''
if s.count(anchor)!=1: raise SystemExit(f'model anchor count={{s.count(anchor)}}')
s=s.replace(anchor,insert,1)

helper='''
@njit(cache=False, inline="always")
def _policy_build_board_hidden(board: np.ndarray, side: int, castling: int, out: np.ndarray) -> None:
    for lane in range(64):
        out[lane] = POLICY_BOARD_B[lane]
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece == EMPTY:
            continue
        plane = (0 if signed_piece > 0 else 6) + abs(signed_piece) - 1
        col = plane * 64 + square
        for lane in range(64):
            out[lane] += POLICY_BOARD_W[lane, col]
    stm = 1.0 if side == WHITE else -1.0
    for lane in range(64):
        out[lane] += POLICY_BOARD_W[lane, 768] * stm
        if castling & 1: out[lane] += POLICY_BOARD_W[lane, 769]
        if castling & 2: out[lane] += POLICY_BOARD_W[lane, 770]
        if castling & 4: out[lane] += POLICY_BOARD_W[lane, 771]
        if castling & 8: out[lane] += POLICY_BOARD_W[lane, 772]
        if out[lane] < 0.0: out[lane] = 0.0


@njit(cache=False, inline="always")
def _policy_score_move(board: np.ndarray, move: int, board_hidden: np.ndarray, move_hidden: np.ndarray, head_hidden: np.ndarray) -> float:
    from_square = move_from(move); to_square = move_to(move); promotion = move_promotion(move)
    mover = abs(int(board[from_square])); captured = abs(int(board[to_square]))
    ep = bool(move & FLAG_EP)
    if ep: captured = PAWN
    for lane in range(64):
        v = POLICY_MOVE_B[lane]
        v += POLICY_MOVE_W[lane, from_square]
        v += POLICY_MOVE_W[lane, 64 + to_square]
        if mover: v += POLICY_MOVE_W[lane, 128 + mover - 1]
        if captured: v += POLICY_MOVE_W[lane, 134 + captured - 1]
        if promotion: v += POLICY_MOVE_W[lane, 140 + promotion - 1]
        if captured or ep: v += POLICY_MOVE_W[lane, 145]
        # feature 146 (`gives_check`) is deliberately zero in the runtime-exact model.
        if move & FLAG_CASTLE: v += POLICY_MOVE_W[lane, 147]
        if ep: v += POLICY_MOVE_W[lane, 148]
        move_hidden[lane] = v if v > 0.0 else 0.0
    for h in range(64):
        v = POLICY_HEAD_B[h]
        for lane in range(64):
            v += POLICY_HEAD_W[h, lane] * board_hidden[lane]
            v += POLICY_HEAD_W[h, 64 + lane] * move_hidden[lane]
        head_hidden[h] = v if v > 0.0 else 0.0
    out = POLICY_OUT_B
    for lane in range(64):
        out += POLICY_OUT_W[lane] * head_hidden[lane]
    return out


@njit(cache=False)
def _order_root_moves_policy(board: np.ndarray, side: int, castling: int, moves: np.ndarray, count: int, preferred: int, scores: np.ndarray) -> None:
    board_hidden = np.empty(64, dtype=np.float32)
    move_hidden = np.empty(64, dtype=np.float32)
    head_hidden = np.empty(64, dtype=np.float32)
    _policy_build_board_hidden(board, side, castling, board_hidden)
    for index in range(count):
        move = int(moves[index])
        policy = _policy_score_move(board, move, board_hidden, move_hidden, head_hidden)
        score = int(policy * POLICY_LOGIT_SCALE)
        if POLICY_BLEND_DIVISOR > 0:
            score += _move_order_score(board, move, -1) // POLICY_BLEND_DIVISOR
        if move == preferred:
            score += 1_000_000_000
        scores[index] = score
    for index in range(1, count):
        move = int(moves[index]); score = int(scores[index]); cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]; scores[cursor + 1] = scores[cursor]; cursor -= 1
        moves[cursor + 1] = move; scores[cursor + 1] = score


'''
root_anchor='''@njit(cache=False)
def _root(
'''
if s.count(root_anchor)!=1: raise SystemExit(f'root anchor count={{s.count(root_anchor)}}')
s=s.replace(root_anchor,helper+root_anchor,1)
old='''    _order_moves(board, moves, count, preferred, score_stack[0])
'''
new='''    _order_root_moves_policy(board, side, castling, moves, count, preferred, score_stack[0])
'''
if s.count(old)!=1: raise SystemExit(f'root order anchor count={{s.count(old)}}')
s=s.replace(old,new,1)
# Policy root list is already fully sorted. Support both raw V14 and presort-patched input.
pick='        _pick_next_scored_move(moves, score_stack[0], index, count)\n'
if s.count(pick)>1: raise SystemExit(f'unexpected root pick count={{s.count(pick)}}')
s=s.replace(pick,'',1)
p.write_text(s)
