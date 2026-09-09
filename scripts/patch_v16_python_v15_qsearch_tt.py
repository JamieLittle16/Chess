#!/usr/bin/env python3
from pathlib import Path
import sys

p=Path(sys.argv[1]); s=p.read_text()

def one(old,new):
    global s
    n=s.count(old)
    if n!=1: raise SystemExit(f'anchor count {n}: {old[:120]!r}')
    s=s.replace(old,new,1)

one('TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\n', 'TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1\nTT_QDEPTH_BASE = 64\nTT_NO_MOVE = TT_MOVE_MASK\n')
one('''@njit(cache=False, inline="always")
def _tt_meta_move(meta: np.uint64) -> int:
    return np.int64(meta & np.uint64(TT_MOVE_MASK))
''','''@njit(cache=False, inline="always")
def _tt_meta_move(meta: np.uint64) -> int:
    raw = np.int64(meta & np.uint64(TT_MOVE_MASK))
    return np.int64(-1) if raw == TT_NO_MOVE else raw
''')

start=s.index('@njit(cache=False)\ndef _quiescence(')
end=s.index('\n\n@njit(cache=False, inline="never")\ndef _is_elementary_dead_material', start)
new_q='''@njit(cache=False, inline="always")
def _qsearch_tt_store(
    current_key: np.uint64,
    current_tt_context: np.uint64,
    q_depth: int,
    best_move: int,
    best_score: int,
    flag: int,
    ply: int,
    tt_table: np.ndarray,
) -> None:
    tt_index = _tt_index(current_key, current_tt_context)
    old_meta = tt_table[TT_META_OFFSET + tt_index]
    same_entry = (
        tt_table[TT_KEYS_OFFSET + tt_index] == current_key
        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context
        and old_meta != np.uint64(0)
    )
    old_depth = _tt_meta_depth(old_meta) if old_meta != np.uint64(0) else -1
    old_generation = _tt_meta_generation(old_meta) if old_meta != np.uint64(0) else 0
    generation = np.int64(tt_table[TT_GENERATION_INDEX] & np.uint64(TT_GENERATION_MASK))
    age = (generation - old_generation) & TT_GENERATION_MASK
    old_is_qsearch = old_depth >= TT_QDEPTH_BASE
    # Qsearch is deliberately a low-priority TT resident. It may refresh/replace qsearch work,
    # fill an empty/aged slot, but it does not evict current-generation full-search information.
    replace = (
        old_meta == np.uint64(0)
        or age >= 2
        or (same_entry and old_is_qsearch and q_depth >= old_depth)
        or ((not same_entry) and old_is_qsearch and q_depth >= old_depth)
    )
    if replace:
        tt_table[TT_KEYS_OFFSET + tt_index] = current_key
        tt_table[TT_CONTEXTS_OFFSET + tt_index] = current_tt_context
        tt_table[TT_META_OFFSET + tt_index] = _tt_pack_meta(
            best_move, q_depth, flag, generation, best_score, ply
        )


@njit(cache=False)
def _quiescence(
    board: np.ndarray,
    side: int,
    castling: int,
    ep_square: int,
    halfmove_clock: int,
    alpha: int,
    beta: int,
    ply: int,
    qply: int,
    nodes: np.ndarray,
    max_nodes: int,
    hard_deadline_ticks: int,
    pseudo_stack: np.ndarray,
    move_stack: np.ndarray,
    score_stack: np.ndarray,
    eval_stack: np.ndarray,
    history_keys: np.ndarray,
    history_count: int,
    path_keys: np.ndarray,
    history_contexts: np.ndarray,
    tt_table: np.ndarray,
) -> tuple[int, bool]:
    if _search_budget_exhausted(nodes, max_nodes, hard_deadline_ticks):
        return 0, True
    if _is_rule_draw(halfmove_clock, ply, history_keys, history_count, path_keys):
        if _state_in_check(board, side, eval_stack[ply]):
            pseudo = pseudo_stack[ply]
            legal = move_stack[ply]
            if _legal_moves_for_state(
                board, side, castling, ep_square, pseudo, legal, eval_stack[ply]
            ) == 0:
                return -MATE + ply, False
        return 0, False
    if _is_elementary_dead_material(board, eval_stack[ply]):
        return 0, False

    current_key = path_keys[ply]
    current_context = history_contexts[ply]
    current_tt_context = _tt_context_identity(current_context, halfmove_clock)
    tt_index = _tt_index(current_key, current_tt_context)
    tt_match = (
        tt_table[TT_KEYS_OFFSET + tt_index] == current_key
        and tt_table[TT_CONTEXTS_OFFSET + tt_index] == current_tt_context
        and tt_table[TT_META_OFFSET + tt_index] != np.uint64(0)
    )
    meta = tt_table[TT_META_OFFSET + tt_index] if tt_match else np.uint64(0)
    tt_preferred = _tt_meta_move(meta) if tt_match else -1
    q_depth = TT_QDEPTH_BASE + max(0, MAX_QPLY - qply)
    if tt_match:
        stored_depth = _tt_meta_depth(meta)
        if stored_depth >= q_depth and stored_depth >= TT_QDEPTH_BASE:
            tt_score = _tt_meta_score(meta, ply)
            tt_flag = _tt_meta_flag(meta)
            if tt_flag == TT_EXACT:
                return tt_score, False
            if tt_flag == TT_LOWER and tt_score >= beta:
                return tt_score, False
            if tt_flag == TT_UPPER and tt_score <= alpha:
                return tt_score, False

    alpha_original = alpha
    checked = _state_in_check(board, side, eval_stack[ply])
    best_score = -INFINITY
    best_move = -1
    if not checked:
        stand_pat = (
            _evaluate_state(side, eval_stack[ply])
            if qply == 0
            else _evaluate_state_v13_only(side, eval_stack[ply])
        )
        best_score = stand_pat
        if stand_pat >= beta:
            _qsearch_tt_store(
                current_key, current_tt_context, q_depth, -1, stand_pat, TT_LOWER, ply, tt_table
            )
            return stand_pat, False
        if stand_pat > alpha:
            alpha = stand_pat
        if qply >= MAX_QPLY:
            flag = TT_EXACT if stand_pat > alpha_original else TT_UPPER
            _qsearch_tt_store(
                current_key, current_tt_context, q_depth, -1, stand_pat, flag, ply, tt_table
            )
            return alpha, False

    pseudo = pseudo_stack[ply]
    moves = move_stack[ply]
    if checked:
        count = _legal_moves_for_state(
            board, side, castling, ep_square, pseudo, moves, eval_stack[ply]
        )
        if count == 0:
            return -MATE + ply, False
        _order_moves(board, moves, count, tt_preferred, score_stack[ply])
    else:
        own_king = int(
            eval_stack[ply][EVAL_WHITE_KING]
            if side == WHITE
            else eval_stack[ply][EVAL_BLACK_KING]
        )
        count = generate_legal_tactical_moves_into_with_king(
            board, side, ep_square, pseudo, moves, own_king
        )
        if count == 0:
            if has_any_legal_move_with_king(
                board, side, castling, ep_square, pseudo, own_king
            ):
                flag = TT_EXACT if best_score > alpha_original else TT_UPPER
                _qsearch_tt_store(
                    current_key, current_tt_context, q_depth, -1, best_score, flag, ply, tt_table
                )
                return alpha, False
            return 0, False
        _order_moves(board, moves, count, tt_preferred, score_stack[ply])

    for index in range(count):
        move = int(moves[index])
        packed_order = int(score_stack[ply, index])
        child_halfmove = 0 if (packed_order & 3) != 0 else halfmove_clock + 1
        _advance_eval_state_into(
            board,
            side,
            move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        path_keys[ply + 1] = _child_position_key(
            board,
            side,
            castling,
            ep_square,
            move,
            child_castling,
            child_ep,
            captured_piece,
            captured_square,
            path_keys[ply],
        )
        history_contexts[ply + 1] = _child_history_context(
            current_context, current_key, child_halfmove
        )
        score, aborted = _quiescence(
            board,
            -side,
            child_castling,
            child_ep,
            child_halfmove,
            -beta,
            -alpha,
            ply + 1,
            qply + 1,
            nodes,
            max_nodes,
            hard_deadline_ticks,
            pseudo_stack,
            move_stack,
            score_stack,
            eval_stack,
            history_keys,
            history_count,
            path_keys,
            history_contexts,
            tt_table,
        )
        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if aborted:
            return 0, True
        score = -score
        if score > best_score:
            best_score = score
            best_move = move
        if score >= beta:
            _qsearch_tt_store(
                current_key, current_tt_context, q_depth, move, score, TT_LOWER, ply, tt_table
            )
            return score, False
        if score > alpha:
            alpha = score

    flag = TT_EXACT if best_score > alpha_original else TT_UPPER
    _qsearch_tt_store(
        current_key, current_tt_context, q_depth, best_move, best_score, flag, ply, tt_table
    )
    return alpha, False
'''
s=s[:start]+new_q+s[end:]

# Wire qsearch's rule-history identity and shared TT through the nominal-leaf boundary.
one('''            history_keys,
            history_count,
            path_keys,
        )

    current_key = path_keys[ply]
''','''            history_keys,
            history_count,
            path_keys,
            history_contexts,
            tt_table,
        )

    current_key = path_keys[ply]
''')

# Full search must never interpret a qsearch marker as a positive-depth bound.
one('''    if tt_match and _tt_meta_depth(meta) >= depth:
        tt_score = _tt_meta_score(meta, ply)
''','''    tt_depth = _tt_meta_depth(meta) if tt_match else -1
    if tt_match and tt_depth < TT_QDEPTH_BASE and tt_depth >= depth:
        tt_score = _tt_meta_score(meta, ply)
''')

# Static audit.
if s.count('TT_QDEPTH_BASE') < 5: raise SystemExit('qdepth marker not wired')
if s.count('history_contexts,\n            tt_table,') < 2: raise SystemExit('qsearch state not wired')
p.write_text(s)
