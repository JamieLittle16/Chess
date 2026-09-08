#!/usr/bin/env python3
"""Replace packaged V14 absolute H64 student with a shared king-bucket student.

The model uses one embedding table but maintains White- and Black-perspective accumulators. Ordinary
non-king moves update both accumulators incrementally. King moves rebuild the student tail from the
virtual child position so bucket changes are exact without changing the search make/unmake order.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_bucket_student_runtime.py SEARCH.py HIDDEN")
p=Path(sys.argv[1]); hidden=int(sys.argv[2])
if hidden not in (16,32): raise SystemExit('HIDDEN must be 16 or 32')
s=p.read_text()

old_model='''_student_model = np.load(Path(__file__).with_name("v14_student_h64.npz"), allow_pickle=False)
STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_OUTPUT_BIAS = int(np.asarray(_student_model["output_bias"], dtype=np.int32).reshape(-1)[0])
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (768, 64):
    raise ValueError("invalid V14 H64 student feature matrix")
if STUDENT_FEATURE_BIAS.shape != (64,) or STUDENT_OUTPUT_WEIGHTS.shape != (64,):
    raise ValueError("invalid V14 H64 student head")
STUDENT_SCALE_NUM = 1
STUDENT_SCALE_DEN = 12
'''
new_model=f'''_student_model = np.load(Path(__file__).with_name("v15_bucket_student.npz"), allow_pickle=False)
STUDENT_HIDDEN = {hidden}
STUDENT_FEATURE_WEIGHTS = np.ascontiguousarray(_student_model["feature_weights"], dtype=np.int16)
STUDENT_FEATURE_BIAS = np.ascontiguousarray(_student_model["feature_bias"], dtype=np.int16)
STUDENT_OUTPUT_WEIGHTS = np.ascontiguousarray(_student_model["output_weights"], dtype=np.int16)
STUDENT_SCALE_DEN = int(np.asarray(_student_model["scale_denominator"], dtype=np.int32).reshape(-1)[0])
del _student_model
if STUDENT_FEATURE_WEIGHTS.shape != (6144, STUDENT_HIDDEN):
    raise ValueError("invalid V15 king-bucket student feature matrix")
if STUDENT_FEATURE_BIAS.shape != (STUDENT_HIDDEN,) or STUDENT_OUTPUT_WEIGHTS.shape != (STUDENT_HIDDEN,):
    raise ValueError("invalid V15 king-bucket student head")
if STUDENT_SCALE_DEN <= 0:
    raise ValueError("invalid V15 king-bucket student scale")
STUDENT_QA = 255
STUDENT_QB = 64
STUDENT_CP_SCALE = 400
'''
if s.count(old_model)!=1: raise SystemExit(f'model anchor count={s.count(old_model)}')
s=s.replace(old_model,new_model,1)

old_layout='''STUDENT_OFFSET = EVAL_V13_WIDTH
STUDENT_HIDDEN = 64
EVAL_WIDTH = EVAL_V13_WIDTH + STUDENT_HIDDEN
'''
new_layout='''STUDENT_WHITE_OFFSET = EVAL_V13_WIDTH
STUDENT_BLACK_OFFSET = STUDENT_WHITE_OFFSET + STUDENT_HIDDEN
EVAL_WIDTH = STUDENT_BLACK_OFFSET + STUDENT_HIDDEN
'''
if s.count(old_layout)!=1: raise SystemExit(f'layout anchor count={s.count(old_layout)}')
s=s.replace(old_layout,new_layout,1)

helper='''
@njit(cache=False, inline="always")
def _bucket_student_feature_index(perspective: int, king_square: int, signed_piece: int, square: int) -> int:
    king_file = king_square & 7
    king_rank = king_square >> 3
    if perspective != WHITE:
        king_rank = 7 - king_rank
    mirror = king_file >= 4
    canonical_king_file = 7 - king_file if mirror else king_file
    bucket = (king_rank // 2) * 2 + (canonical_king_file // 2)
    same_owner = (signed_piece > 0) == (perspective == WHITE)
    ownership = 0 if same_owner else 1
    plane = ownership * 6 + (abs(signed_piece) - 1)
    file = square & 7
    rank = square >> 3
    if perspective != WHITE:
        rank = 7 - rank
    if mirror:
        file = 7 - file
    return bucket * 768 + plane * 64 + rank * 8 + file


@njit(cache=False, inline="always")
def _bucket_student_add_piece(acc: np.ndarray, perspective: int, king_square: int, signed_piece: int, square: int, sign: int) -> None:
    index = _bucket_student_feature_index(perspective, king_square, signed_piece, square)
    for lane in range(STUDENT_HIDDEN):
        acc[lane] += sign * int(STUDENT_FEATURE_WEIGHTS[index, lane])


@njit(cache=False, inline="always")
def _bucket_student_reset(acc: np.ndarray) -> None:
    for lane in range(STUDENT_HIDDEN):
        acc[lane] = int(STUDENT_FEATURE_BIAS[lane])


@njit(cache=False)
def _build_bucket_student_into(board: np.ndarray, state: np.ndarray) -> None:
    white = state[STUDENT_WHITE_OFFSET:STUDENT_BLACK_OFFSET]
    black = state[STUDENT_BLACK_OFFSET:EVAL_WIDTH]
    _bucket_student_reset(white); _bucket_student_reset(black)
    white_king = int(state[EVAL_WHITE_KING]); black_king = int(state[EVAL_BLACK_KING])
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece != EMPTY:
            _bucket_student_add_piece(white, WHITE, white_king, signed_piece, square, 1)
            _bucket_student_add_piece(black, -WHITE, black_king, signed_piece, square, 1)


@njit(cache=False, inline="always")
def _bucket_student_virtual_rebuild_after_king_move(board: np.ndarray, side: int, move: int, child: np.ndarray) -> None:
    white = child[STUDENT_WHITE_OFFSET:STUDENT_BLACK_OFFSET]
    black = child[STUDENT_BLACK_OFFSET:EVAL_WIDTH]
    _bucket_student_reset(white); _bucket_student_reset(black)
    white_king = int(child[EVAL_WHITE_KING]); black_king = int(child[EVAL_BLACK_KING])
    from_square=move_from(move); to_square=move_to(move); promotion=move_promotion(move)
    moving_signed=int(board[from_square]); moving_piece=abs(moving_signed)
    captured_square=to_square
    if move & FLAG_EP: captured_square=to_square-8*side
    rook_from=-1; rook_to=-1
    if move & FLAG_CASTLE:
        if to_square==6: rook_from,rook_to=7,5
        elif to_square==2: rook_from,rook_to=0,3
        elif to_square==62: rook_from,rook_to=63,61
        else: rook_from,rook_to=56,59
    for square in range(64):
        if square==from_square or square==captured_square or square==rook_from:
            continue
        signed_piece=int(board[square])
        if signed_piece==EMPTY: continue
        _bucket_student_add_piece(white,WHITE,white_king,signed_piece,square,1)
        _bucket_student_add_piece(black,-WHITE,black_king,signed_piece,square,1)
    placed_signed=side*promotion if promotion else side*moving_piece
    _bucket_student_add_piece(white,WHITE,white_king,placed_signed,to_square,1)
    _bucket_student_add_piece(black,-WHITE,black_king,placed_signed,to_square,1)
    if rook_from>=0:
        rook_signed=side*ROOK
        _bucket_student_add_piece(white,WHITE,white_king,rook_signed,rook_to,1)
        _bucket_student_add_piece(black,-WHITE,black_king,rook_signed,rook_to,1)


@njit(cache=False, inline="always")
def _advance_bucket_student_into(board: np.ndarray, side: int, move: int, parent: np.ndarray, child: np.ndarray) -> None:
    if parent.shape[0] < EVAL_WIDTH or child.shape[0] < EVAL_WIDTH:
        return
    from_square=move_from(move); to_square=move_to(move); promotion=move_promotion(move)
    moving_signed=int(board[from_square]); moving_piece=abs(moving_signed)
    if moving_piece==KING:
        _bucket_student_virtual_rebuild_after_king_move(board,side,move,child)
        return
    for lane in range(STUDENT_HIDDEN):
        child[STUDENT_WHITE_OFFSET+lane]=parent[STUDENT_WHITE_OFFSET+lane]
        child[STUDENT_BLACK_OFFSET+lane]=parent[STUDENT_BLACK_OFFSET+lane]
    captured_square=to_square; captured_signed=int(board[to_square])
    if move & FLAG_EP:
        captured_square=to_square-8*side; captured_signed=int(board[captured_square])
    placed_signed=side*promotion if promotion else moving_signed
    white_king=int(parent[EVAL_WHITE_KING]); black_king=int(parent[EVAL_BLACK_KING])
    white=child[STUDENT_WHITE_OFFSET:STUDENT_BLACK_OFFSET]; black=child[STUDENT_BLACK_OFFSET:EVAL_WIDTH]
    _bucket_student_add_piece(white,WHITE,white_king,moving_signed,from_square,-1)
    _bucket_student_add_piece(black,-WHITE,black_king,moving_signed,from_square,-1)
    if captured_signed!=EMPTY:
        _bucket_student_add_piece(white,WHITE,white_king,captured_signed,captured_square,-1)
        _bucket_student_add_piece(black,-WHITE,black_king,captured_signed,captured_square,-1)
    _bucket_student_add_piece(white,WHITE,white_king,placed_signed,to_square,1)
    _bucket_student_add_piece(black,-WHITE,black_king,placed_signed,to_square,1)


@njit(cache=False, inline="always")
def _infer_bucket_student_white_cp(state: np.ndarray) -> int:
    raw=np.int64(0)
    for lane in range(STUDENT_HIDDEN):
        w=int(state[STUDENT_WHITE_OFFSET+lane]); b=int(state[STUDENT_BLACK_OFFSET+lane])
        if w<0: w=0
        elif w>STUDENT_QA: w=STUDENT_QA
        if b<0: b=0
        elif b>STUDENT_QA: b=STUDENT_QA
        raw += np.int64(w*w-b*b)*np.int64(STUDENT_OUTPUT_WEIGHTS[lane])
    scaled=trunc_div_scalar(raw,STUDENT_QA)
    cp=trunc_div_scalar(scaled*STUDENT_CP_SCALE,STUDENT_QA*STUDENT_QB)
    return trunc_div_scalar(cp,STUDENT_SCALE_DEN)


'''
anchor='''@njit(cache=False)
def _build_eval_state_into(board: np.ndarray, state: np.ndarray) -> None:
'''
if s.count(anchor)!=1: raise SystemExit(f'build function anchor count={s.count(anchor)}')
s=s.replace(anchor,helper+anchor,1)

old_build='''    build_absolute768_accumulator_into(
        board,
        STUDENT_FEATURE_WEIGHTS,
        STUDENT_FEATURE_BIAS,
        state[STUDENT_OFFSET:EVAL_WIDTH],
    )
'''
new_build='''    _build_bucket_student_into(board, state)
'''
if s.count(old_build)!=1: raise SystemExit(f'build student anchor count={s.count(old_build)}')
s=s.replace(old_build,new_build,1)

old_eval='''    student_cp = infer_absolute768_student_cp(
        state[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_OUTPUT_WEIGHTS,
        STUDENT_OUTPUT_BIAS,
    )
    if side != WHITE:
        student_cp = -student_cp
    student_cp = trunc_div_scalar(student_cp * STUDENT_SCALE_NUM, STUDENT_SCALE_DEN)
    return score + correction + student_cp
'''
new_eval='''    student_cp = _infer_bucket_student_white_cp(state)
    if side != WHITE:
        student_cp = -student_cp
    return score + correction + student_cp
'''
if s.count(old_eval)!=1: raise SystemExit(f'eval student anchor count={s.count(old_eval)}')
s=s.replace(old_eval,new_eval,1)

old_adv='''    advance_absolute768_accumulator_into(
        board,
        side,
        move,
        parent[STUDENT_OFFSET:EVAL_WIDTH],
        child[STUDENT_OFFSET:EVAL_WIDTH],
        STUDENT_FEATURE_WEIGHTS,
    )
'''
new_adv='''    _advance_bucket_student_into(board, side, move, parent, child)
'''
if s.count(old_adv)!=1: raise SystemExit(f'advance student anchor count={s.count(old_adv)}')
s=s.replace(old_adv,new_adv,1)
p.write_text(s)
