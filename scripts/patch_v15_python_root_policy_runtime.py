#!/usr/bin/env python3
"""Add a root-only NumPy policy hint to packaged V14 without changing interior search policy."""
from pathlib import Path
import sys

if len(sys.argv)!=3: raise SystemExit('usage: patch_v15_python_root_policy_runtime.py AGENT.py SEARCH.py')
agent=Path(sys.argv[1]); search=Path(sys.argv[2]); a=agent.read_text(); s=search.read_text()

# Extend timed cached search with one initial root hint. Existing compatibility wrapper passes -1.
old='''    max_nodes: int,
    hash_keys: np.ndarray,
    hash_moves: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, int, int, int]:
'''
new='''    max_nodes: int,
    root_hint: int,
    hash_keys: np.ndarray,
    hash_moves: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, int, int, int]:
'''
if s.count(old)!=1: raise SystemExit(f'timed signature anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''    for depth in range(1, MAX_DEPTH + 1):
        iter_start_ticks = int(_CPU_CLOCK())
        move, score, aborted = _root(
            board, side, castling, ep_square, halfmove_clock, depth, best_move, nodes, max_nodes,
'''
new='''    for depth in range(1, MAX_DEPTH + 1):
        iter_start_ticks = int(_CPU_CLOCK())
        preferred_root = root_hint if depth == 1 and root_hint >= 0 else best_move
        move, score, aborted = _root(
            board, side, castling, ep_square, halfmove_clock, depth, preferred_root, nodes, max_nodes,
'''
if s.count(old)!=1: raise SystemExit(f'timed loop anchor count={s.count(old)}')
s=s.replace(old,new,1)

old='''        soft_ms, hard_ms, max_nodes, hash_keys, hash_moves,
        tt_table
'''
new='''        soft_ms, hard_ms, max_nodes, -1, hash_keys, hash_moves,
        tt_table
'''
if s.count(old)!=1: raise SystemExit(f'compat call anchor count={s.count(old)}')
s=s.replace(old,new,1)
search.write_text(s)

# Agent imports move encoder/flags and loads the small NumPy policy.
old='''from experiments.numba_core import encode_position, move_to_uci
'''
new='''from experiments.numba_core import (
    FLAG_CASTLE, FLAG_DOUBLE, FLAG_EP, KING, PAWN,
    encode_move, encode_position, move_to_uci,
)
'''
if a.count(old)!=1: raise SystemExit(f'agent core import anchor count={a.count(old)}')
a=a.replace(old,new,1)

model='''
_POLICY_MODEL = np.load(Path(__file__).with_name("v15_root_policy_h64.npz"), allow_pickle=False)
_POLICY_BOARD_W = np.ascontiguousarray(_POLICY_MODEL["board_w"], dtype=np.float32)
_POLICY_BOARD_B = np.ascontiguousarray(_POLICY_MODEL["board_b"], dtype=np.float32)
_POLICY_MOVE_W = np.ascontiguousarray(_POLICY_MODEL["move_w"], dtype=np.float32)
_POLICY_MOVE_B = np.ascontiguousarray(_POLICY_MODEL["move_b"], dtype=np.float32)
_POLICY_HEAD_W = np.ascontiguousarray(_POLICY_MODEL["head_w"], dtype=np.float32)
_POLICY_HEAD_B = np.ascontiguousarray(_POLICY_MODEL["head_b"], dtype=np.float32)
_POLICY_OUT_W = np.ascontiguousarray(_POLICY_MODEL["out_w"], dtype=np.float32).reshape(-1)
_POLICY_OUT_B = float(np.asarray(_POLICY_MODEL["out_b"], dtype=np.float32).reshape(-1)[0])
del _POLICY_MODEL
if _POLICY_BOARD_W.shape != (64, 773) or _POLICY_MOVE_W.shape != (64, 149):
    raise ValueError("invalid V15 root policy")


def _policy_board_features(board: chess.Board) -> np.ndarray:
    x=np.zeros(773,dtype=np.float32)
    for sq,piece in board.piece_map().items():
        plane=(0 if piece.color==chess.WHITE else 6)+piece.piece_type-1
        x[plane*64+sq]=1.0
    off=768;x[off]=1.0 if board.turn==chess.WHITE else -1.0
    x[off+1]=float(board.has_kingside_castling_rights(chess.WHITE));x[off+2]=float(board.has_queenside_castling_rights(chess.WHITE))
    x[off+3]=float(board.has_kingside_castling_rights(chess.BLACK));x[off+4]=float(board.has_queenside_castling_rights(chess.BLACK))
    return x


def _policy_move_matrix(board: chess.Board, moves: list[chess.Move]) -> np.ndarray:
    x=np.zeros((len(moves),149),dtype=np.float32)
    for i,m in enumerate(moves):
        o=0;x[i,o+m.from_square]=1.0;o+=64;x[i,o+m.to_square]=1.0;o+=64
        p=board.piece_at(m.from_square)
        if p is not None:x[i,o+p.piece_type-1]=1.0
        o+=6;c=board.piece_at(m.to_square)
        if board.is_en_passant(m):x[i,o]=1.0
        elif c is not None:x[i,o+c.piece_type-1]=1.0
        o+=6
        if m.promotion is not None:x[i,o+m.promotion-1]=1.0
        o+=5;x[i,o]=float(board.is_capture(m));x[i,o+1]=float(board.gives_check(m));x[i,o+2]=float(board.is_castling(m));x[i,o+3]=float(board.is_en_passant(m))
    return x


def _policy_encoded_move(board: chess.Board, move: chess.Move) -> int:
    flags=0;piece=board.piece_at(move.from_square)
    if board.is_en_passant(move):flags|=FLAG_EP
    if board.is_castling(move):flags|=FLAG_CASTLE
    if piece is not None and piece.piece_type==PAWN and abs(move.to_square-move.from_square)==16:flags|=FLAG_DOUBLE
    return int(encode_move(move.from_square,move.to_square,move.promotion or 0,flags))


def _root_policy_hint(board: chess.Board, legal_moves: list[chess.Move]) -> int:
    if not legal_moves:return -1
    bx=_policy_board_features(board)
    bh=np.maximum(_POLICY_BOARD_W @ bx + _POLICY_BOARD_B,0.0)
    mx=_policy_move_matrix(board,legal_moves)
    mh=np.maximum(mx @ _POLICY_MOVE_W.T + _POLICY_MOVE_B,0.0)
    both=np.concatenate((np.repeat(bh[None,:],len(legal_moves),axis=0),mh),axis=1)
    hh=np.maximum(both @ _POLICY_HEAD_W.T + _POLICY_HEAD_B,0.0)
    scores=hh @ _POLICY_OUT_W + _POLICY_OUT_B
    return _policy_encoded_move(board,legal_moves[int(np.argmax(scores))])

'''
anchor='''# Import/JIT time is outside the game clock. We intentionally compile and calibrate here.
'''
if a.count(anchor)!=1: raise SystemExit(f'agent model insertion anchor count={a.count(anchor)}')
a=a.replace(anchor,model+anchor,1)

# Warmup timed call.
old='''        20,
        250_000,
        _HASH_KEYS,
'''
new='''        20,
        250_000,
        -1,
        _HASH_KEYS,
'''
if a.count(old)!=1: raise SystemExit(f'warmup call anchor count={a.count(old)}')
a=a.replace(old,new,1)

# Runtime call computes the policy once before entering Numba.
old='''    move, score, depth, nodes = iterative_search_stateful_timed_cached(
        encoded.board,
        encoded.side,
        encoded.castling,
        encoded.ep_square,
        board.halfmove_clock,
        history_keys,
        len(history_keys),
        soft_ms,
        hard_ms,
        _MAX_NODE_BUDGET,
        _HASH_KEYS,
'''
new='''    root_hint = _root_policy_hint(board, legal_moves)
    move, score, depth, nodes = iterative_search_stateful_timed_cached(
        encoded.board,
        encoded.side,
        encoded.castling,
        encoded.ep_square,
        board.halfmove_clock,
        history_keys,
        len(history_keys),
        soft_ms,
        hard_ms,
        _MAX_NODE_BUDGET,
        root_hint,
        _HASH_KEYS,
'''
if a.count(old)!=1: raise SystemExit(f'production call anchor count={a.count(old)}')
a=a.replace(old,new,1)
agent.write_text(a)
