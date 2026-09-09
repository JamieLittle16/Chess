#!/usr/bin/env python3
"""Reuse move-order classification in the recursive hot path.

Scores keep their exact ordering semantics. Four low packed bits carry the moving piece kind and
whether the move is tactical, allowing search/qsearch to avoid repeated board probes for tactical
classification, halfmove-clock reset, and quiet-history context construction.

Apply after presort + Rust-history + lazy-student patching.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_move_meta.py SEARCH.py")
p = Path(sys.argv[1])
s = p.read_text()

# Replace ordinary ordering with an exact-score + 4-bit metadata pack.
start = s.index('@njit(cache=False)\ndef _order_moves(')
end = s.index('\n\n@njit(cache=False, inline="always")\ndef _pick_next_scored_move', start)
new = '''@njit(cache=False, inline="always")
def _move_order_score_meta4(board: np.ndarray, move: int, preferred: int) -> int:
    from_square = move_from(move)
    to_square = move_to(move)
    promotion = move_promotion(move)
    signed_attacker = int(board[from_square])
    attacker = abs(signed_attacker)
    target = abs(int(board[to_square]))
    ep = bool(move & FLAG_EP)
    if ep:
        target = PAWN

    if move == preferred:
        score = 10_000_000
    else:
        score = 0
        if target:
            score += 7_000_000 + 16 * int(PIECE_VALUE[target]) - int(PIECE_VALUE[attacker])
        if promotion:
            score += 6_000_000 + int(PIECE_VALUE[promotion])
        if attacker == PAWN and target == 0 and not ep and promotion == 0:
            raw_rank = to_square >> 3
            relative_rank = raw_rank if signed_attacker > 0 else 7 - raw_rank
            if relative_rank == 6:
                score += 5_200_000
        score += int(ORDER_CENTER_BONUS[to_square])

    tactical = ep or target != 0 or promotion != 0
    # bits 1..3: zero-based moving piece kind; bit 0: capture/EP/promotion.
    meta = ((attacker - 1) << 1) | (1 if tactical else 0)
    return score * 16 + meta


@njit(cache=False)
def _order_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
) -> None:
    """Score once; stable-sort by the exact legacy score while carrying metadata."""
    for index in range(count):
        scores[index] = _move_order_score_meta4(board, int(moves[index]), preferred)
    for index in range(1, count):
        move = int(moves[index])
        packed = int(scores[index])
        score = packed >> 4
        cursor = index - 1
        while cursor >= 0 and (int(scores[cursor]) >> 4) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = packed
'''
s = s[:start] + new + s[end:]

# Replace Rust-history ordering with the same score pack. Learned quiet-history values remain
# exactly where they were in the score before packing, and equal scores remain generator-stable.
start = s.index('@njit(cache=False)\ndef _order_moves_with_killers(')
end = s.index('\n\n@njit(cache=False)\ndef _is_tactical', start)
new = '''@njit(cache=False)
def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    side: int,
    previous_context: int,
    quiet_history: np.ndarray,
) -> None:
    """Order PV/tacticals, killers and history quiets once while carrying move metadata."""
    for index in range(count):
        move = int(moves[index])
        packed = _move_order_score_meta4(board, move, preferred)
        score = packed >> 4
        meta = packed & 15
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            else:
                attacker_index = meta >> 1
                context = attacker_index * 64 + move_to(move)
                score += _quiet_history_score(side, previous_context, context, quiet_history)
        scores[index] = score * 16 + meta
    for index in range(1, count):
        move = int(moves[index])
        packed = int(scores[index])
        score = packed >> 4
        cursor = index - 1
        while cursor >= 0 and (int(scores[cursor]) >> 4) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = packed
'''
s = s[:start] + new + s[end:]

# Qsearch: all required fifty-move information is already encoded by ordering.
q0 = s.index('@njit(cache=False)\ndef _quiescence(')
q1 = s.index('\n\n@njit(cache=False, inline="never")\ndef _is_elementary_dead_material', q0)
q = s[q0:q1]
old = '''    for index in range(count):
        move = int(moves[index])
        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)
'''
newq = '''    for index in range(count):
        move = int(moves[index])
        meta = int(score_stack[ply, index]) & 15
        attacker_index = meta >> 1
        child_halfmove = 0 if (meta & 1) != 0 or attacker_index == 0 else halfmove_clock + 1
'''
if q.count(old) != 1:
    raise SystemExit(f"qsearch metadata anchor count={q.count(old)}")
q = q.replace(old, newq, 1)
s = s[:q0] + q + s[q1:]

# Main recursive loop: perform small line-local substitutions so this stays robust to the lazy-H64
# prefix update block inserted between halfmove handling and make_move_inplace.
n0 = s.index('@njit(cache=False)\ndef _negamax(')
n1 = s.index('\n\n@njit(cache=False)\ndef _root(', n0)
n = s[n0:n1]
repls = [
    (
        '        order_score = int(score_stack[ply, index])\n',
        '        packed_order = int(score_stack[ply, index])\n'
        '        order_score = packed_order >> 4\n'
        '        meta = packed_order & 15\n'
        '        attacker_index = meta >> 1\n',
    ),
    ('        quiet = not _is_tactical(board, move)\n', '        quiet = (meta & 1) == 0\n'),
    (
        '        current_move_context = _quiet_history_context(board, move)\n',
        '        current_move_context = attacker_index * 64 + move_to(move)\n',
    ),
    (
        '        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n',
        '        child_halfmove = 0 if (meta & 1) != 0 or attacker_index == 0 else halfmove_clock + 1\n',
    ),
    (
        '        moving_signed = int(board[move_from(move)])\n',
        '        moving_signed = side * (attacker_index + 1)\n',
    ),
]
for old, new in repls:
    if n.count(old) != 1:
        raise SystemExit(f"negamax metadata anchor count={n.count(old)} for {old.strip()}")
    n = n.replace(old, new, 1)
s = s[:n0] + n + s[n1:]

# Root uses the same packed metadata, preserving the exact root ordering score.
r0 = s.index('@njit(cache=False)\ndef _root(')
r1 = s.index('\n\n@njit(cache=False)\ndef iterative_search_stateful(', r0)
r = s[r0:r1]
old = '''        move = int(moves[index])
        move_context_stack[0] = np.int16(_quiet_history_context(board, move))
        child_depth = depth - 1
'''
newr = '''        move = int(moves[index])
        packed_order = int(score_stack[0, index])
        meta = packed_order & 15
        attacker_index = meta >> 1
        move_context_stack[0] = np.int16(attacker_index * 64 + move_to(move))
        child_depth = depth - 1
'''
if r.count(old) != 1:
    raise SystemExit(f"root context anchor count={r.count(old)}")
r = r.replace(old, newr, 1)
old = '        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)\n'
newr2 = '        child_halfmove = 0 if (meta & 1) != 0 or attacker_index == 0 else halfmove_clock + 1\n'
if r.count(old) != 1:
    raise SystemExit(f"root halfmove anchor count={r.count(old)}")
r = r.replace(old, newr2, 1)
s = s[:r0] + r + s[r1:]

p.write_text(s)
