from pathlib import Path
import sys
p=Path(sys.argv[1]); top_k=int(sys.argv[2]); s=p.read_text()

def rep(old,new,n=1,label=''):
    global s
    c=s.count(old)
    if c!=n: raise SystemExit(f'{label} count={c} expected={n}')
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
rep(anchor,insert,label='policy load')
rep('''    BISHOP,
    EMPTY,
    FLAG_CASTLE,
''','''    BISHOP,
    CASTLE_BK,
    CASTLE_BQ,
    CASTLE_WK,
    CASTLE_WQ,
    EMPTY,
    FLAG_CASTLE,
''',label='imports')
marker='''@njit(cache=False)
def _order_moves(
'''
helpers=r'''@njit(cache=False, inline="always")
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
def _policy_move_logit(board: np.ndarray, move: int, board_hidden: np.ndarray, move_hidden: np.ndarray, head_hidden: np.ndarray) -> float:
    from_square = move_from(move); to_square = move_to(move)
    moving = abs(int(board[from_square])); captured = PAWN if (move & FLAG_EP) else abs(int(board[to_square])); promotion = move_promotion(move)
    for h in range(64):
        value = float(POLICY_MOVE_B[h]) + float(POLICY_MOVE_W[h, from_square]) + float(POLICY_MOVE_W[h, 64 + to_square])
        if moving: value += float(POLICY_MOVE_W[h, 128 + moving - 1])
        if captured: value += float(POLICY_MOVE_W[h, 134 + captured - 1])
        if promotion: value += float(POLICY_MOVE_W[h, 140 + promotion - 1])
        if captured or (move & FLAG_EP): value += float(POLICY_MOVE_W[h, 145])
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
    for h in range(64): score += float(POLICY_OUT_W[h]) * float(head_hidden[h])
    return score


@njit(cache=False)
def _compute_policy_moves(board: np.ndarray, side: int, castling: int, moves: np.ndarray, count: int, out_moves: np.ndarray) -> int:
    if count <= 0: return 0
    board_hidden=np.empty(64,dtype=np.float32); move_hidden=np.empty(64,dtype=np.float32); head_hidden=np.empty(64,dtype=np.float32)
    scores=np.empty(MAX_MOVES,dtype=np.float32); _policy_board_hidden(board,side,castling,board_hidden)
    for i in range(count): scores[i]=_policy_move_logit(board,int(moves[i]),board_hidden,move_hidden,head_hidden)
    limit=min(POLICY_TOP_K,count)
    for index in range(limit):
        best=index; best_score=float(scores[index])
        for candidate in range(index+1,count):
            value=float(scores[candidate])
            if value>best_score: best=candidate; best_score=value
        out_moves[index]=int(moves[best])
        scores[best]=np.float32(-1.0e30)
    return limit


@njit(cache=False, inline="always")
def _apply_policy_moves(moves: np.ndarray, scores: np.ndarray, count: int, preferred: int, policy_moves: np.ndarray, policy_count: int) -> None:
    cursor=1 if count>0 and int(moves[0])==preferred else 0
    for p in range(policy_count):
        target=int(policy_moves[p])
        if target<0 or target==preferred: continue
        found=-1
        for i in range(cursor,count):
            if int(moves[i])==target: found=i; break
        if found<0: continue
        move=int(moves[found]); score=int(scores[found])
        while found>cursor:
            moves[found]=moves[found-1]; scores[found]=scores[found-1]; found-=1
        moves[cursor]=move; scores[cursor]=score; cursor+=1


@njit(cache=False)
def _order_moves(
'''
rep(marker,helpers,label='helpers')
rep('''    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, int, bool]:
''','''    history_contexts: np.ndarray,
    policy_moves: np.ndarray,
    policy_count: int,
    tt_table: np.ndarray,
) -> tuple[int, int, bool]:
''',label='root sig')
rep('''    _order_moves(board, moves, count, preferred, score_stack[0])

    best_move = int(moves[0])
''','''    _order_moves(board, moves, count, preferred, score_stack[0])
    _apply_policy_moves(moves, score_stack[0], count, preferred, policy_moves, policy_count)

    best_move = int(moves[0])
''',label='root apply')
needle='''    if count == 0:
        return -1, 0, 0, 0

'''
add='''    if count == 0:
        return -1, 0, 0, 0
    policy_moves = np.full(POLICY_TOP_K, -1, dtype=np.int32)
    policy_count = _compute_policy_moves(board, side, castling, move_stack[0], count, policy_moves)

'''
rep(needle,add,n=3,label='policy precompute')
rep('''            history_contexts,
            tt_table,
''','''            history_contexts,
            policy_moves,
            policy_count,
            tt_table,
''',n=1,label='root call long')
rep('''            killers, hash_keys, hash_moves, history_contexts,
            tt_table,
''','''            killers, hash_keys, hash_moves, history_contexts,
            policy_moves, policy_count, tt_table,
''',n=2,label='root calls compact')
p.write_text(s)
