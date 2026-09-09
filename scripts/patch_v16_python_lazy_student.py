#!/usr/bin/env python3
"""Port V15's lazy H64 accumulator materialisation onto the V16 Rust-history search.

The V13 prefix remains eagerly incremental because legality/check/RFP use it throughout the tree.
The 64-lane student tail is represented as pending move edges and is materialised only when a
node actually enters qsearch, where qply=0 consumes the H64 score. This is intended to be an exact
hot-path optimisation: move ordering, pruning, bounds and evaluation values must not change.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_lazy_student.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

anchor = '''@njit(cache=False, inline="always")
def _repetition_piece_index'''
insert = '''STUDENT_EDGE_INVALID = np.uint64(0x8000000000000000)
STUDENT_EDGE_MOVE_MASK = np.uint64((1 << 18) - 1)


@njit(cache=False, inline="always")
def _pack_student_edge(move: int, moving_signed: int, captured_signed: int) -> np.uint64:
    return (
        STUDENT_EDGE_INVALID
        | np.uint64(move & ((1 << 18) - 1))
        | (np.uint64((moving_signed + 6) & 15) << np.uint64(18))
        | (np.uint64((captured_signed + 6) & 15) << np.uint64(22))
    )


@njit(cache=False, inline="always")
def _advance_student_edge_into(edge: np.uint64, parent: np.ndarray, child: np.ndarray) -> None:
    move = int(edge & STUDENT_EDGE_MOVE_MASK)
    moving_signed = int((edge >> np.uint64(18)) & np.uint64(15)) - 6
    captured_signed = int((edge >> np.uint64(22)) & np.uint64(15)) - 6
    side = WHITE if moving_signed > 0 else -WHITE
    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    placed_signed = side * promotion if promotion else moving_signed

    from_feature = (0 if moving_signed > 0 else 384) + (abs(moving_signed) - 1) * 64 + from_square
    to_feature = (0 if placed_signed > 0 else 384) + (abs(placed_signed) - 1) * 64 + to_square
    captured_feature = -1
    if captured_signed != EMPTY:
        captured_square = to_square - 8 * side if move & FLAG_EP else to_square
        captured_feature = (0 if captured_signed > 0 else 384) + (abs(captured_signed) - 1) * 64 + captured_square

    rook_from_feature = -1
    rook_to_feature = -1
    if move & FLAG_CASTLE:
        if to_square == 6:
            rook_from, rook_to = 7, 5
        elif to_square == 2:
            rook_from, rook_to = 0, 3
        elif to_square == 62:
            rook_from, rook_to = 63, 61
        else:
            rook_from, rook_to = 56, 59
        rook_signed = side * ROOK
        rook_from_feature = (0 if rook_signed > 0 else 384) + (ROOK - 1) * 64 + rook_from
        rook_to_feature = (0 if rook_signed > 0 else 384) + (ROOK - 1) * 64 + rook_to

    for neuron in range(STUDENT_HIDDEN):
        value = int(parent[neuron])
        value -= int(STUDENT_FEATURE_WEIGHTS[from_feature, neuron])
        if captured_feature >= 0:
            value -= int(STUDENT_FEATURE_WEIGHTS[captured_feature, neuron])
        value += int(STUDENT_FEATURE_WEIGHTS[to_feature, neuron])
        if rook_from_feature >= 0:
            value -= int(STUDENT_FEATURE_WEIGHTS[rook_from_feature, neuron])
            value += int(STUDENT_FEATURE_WEIGHTS[rook_to_feature, neuron])
        child[neuron] = value


@njit(cache=False, inline="always")
def _materialize_student_path(eval_stack: np.ndarray, student_edges: np.ndarray, ply: int) -> None:
    base = ply
    while base > 0 and (student_edges[base] & STUDENT_EDGE_INVALID) != np.uint64(0):
        base -= 1
    level = base + 1
    while level <= ply:
        edge = student_edges[level]
        if (edge & STUDENT_EDGE_INVALID) != np.uint64(0):
            _advance_student_edge_into(
                edge,
                eval_stack[level - 1, STUDENT_OFFSET:EVAL_WIDTH],
                eval_stack[level, STUDENT_OFFSET:EVAL_WIDTH],
            )
            student_edges[level] = np.uint64(0)
        level += 1


@njit(cache=False, inline="always")
def _repetition_piece_index'''
if s.count(anchor) != 1:
    raise SystemExit(f"student helper anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

old = '''    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
) -> tuple[int, bool]:'''
new = '''    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
    student_edges: np.ndarray,
) -> tuple[int, bool]:'''
if s.count(old) != 1:
    raise SystemExit(f"negamax signature anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
) -> tuple[int, int, bool]:'''
new = '''    tt_table: np.ndarray,
    quiet_history: np.ndarray,
    move_context_stack: np.ndarray,
    student_edges: np.ndarray,
) -> tuple[int, int, bool]:'''
if s.count(old) != 1:
    raise SystemExit(f"root signature anchor count={s.count(old)}")
s = s.replace(old, new, 1)

# Every recursive/root call already ends in the two history arguments after the Rust-history patch.
call_tail = 'tt_table, quiet_history, move_context_stack,'
call_count = s.count(call_tail)
if call_count < 4:
    raise SystemExit(f"history call tail count={call_count}")
s = s.replace(call_tail, 'tt_table, quiet_history, move_context_stack, student_edges,')

alloc = '    move_context_stack = np.full(MAX_PLY, -1, dtype=np.int16)\n'
alloc_count = s.count(alloc)
if alloc_count != 3:
    raise SystemExit(f"move-context allocation count={alloc_count}")
s = s.replace(alloc, alloc + '    student_edges = np.zeros(MAX_PLY, dtype=np.uint64)\n')

old = '''    if depth <= 0:
        return _quiescence('''
new = '''    if depth <= 0:
        _materialize_student_path(eval_stack, student_edges, ply)
        return _quiescence('''
if s.count(old) != 1:
    raise SystemExit(f"qsearch entry anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        _advance_eval_state_into(board, side, move, eval_stack[ply], eval_stack[ply + 1])
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
'''
new = '''        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
        moving_signed = int(board[move_from(move)])
        _advance_eval_state_into(
            board, side, move,
            eval_stack[ply, :EVAL_V13_WIDTH],
            eval_stack[ply + 1, :EVAL_V13_WIDTH],
        )
        child_castling, child_ep, captured_piece, captured_square = make_move_inplace(
            board, side, castling, ep_square, move
        )
        student_edges[ply + 1] = _pack_student_edge(move, moving_signed, captured_piece)
'''
if s.count(old) != 1:
    raise SystemExit(f"recursive eval advance anchor count={s.count(old)}")
s = s.replace(old, new, 1)

p.write_text(s)
