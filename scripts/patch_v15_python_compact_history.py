#!/usr/bin/env python3
"""Add a tiny Numba-native quiet-history table to exact packaged V14.

The full Rust-style main+continuation history port was too expensive in Python.  This experiment
keeps only side x moving-piece-kind x destination (2*6*64 int16 cells), updates one searched quiet
at a time on scout evidence, and optionally lets strong history rescue one LMR ply.  There is no
continuation table, no per-ply context stack and no prior-quiet malus loop.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_compact_history.py SEARCH.py MODE")
p = Path(sys.argv[1])
mode = sys.argv[2]
if mode not in ("order", "both"):
    raise SystemExit("MODE must be order or both")
s = p.read_text()


def rep(old: str, new: str, expected: int, label: str) -> None:
    global s
    count = s.count(old)
    if count != expected:
        raise SystemExit(f"{label} count={count} expected={expected}")
    s = s.replace(old, new, expected)


anchor = "MAX_QPLY = 10\n"
rep(
    anchor,
    anchor
    + f'''\n# V15 compact main-history experiment: side x moving-piece-kind x destination.\nMAIN_HISTORY_LIMIT = 16_384\nMAIN_HISTORY_GOOD = 1_200\nMAIN_HISTORY_USE_LMR = {1 if mode == "both" else 0}\n''',
    1,
    "MAX_QPLY",
)

old = '''@njit(cache=False)\ndef _order_moves_with_killers(\n    board: np.ndarray,\n    moves: np.ndarray,\n    count: int,\n    preferred: int,\n    scores: np.ndarray,\n    killer0: int,\n    killer1: int,\n) -> None:\n    \"\"\"Order PV/tacticals first, then two quiet killers, then ordinary quiets.\"\"\"\n    for index in range(count):\n        move = int(moves[index])\n        score = _move_order_score(board, move, preferred)\n        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n        scores[index] = score\n'''
new = '''@njit(cache=False, inline="always")\ndef _main_history_value(board: np.ndarray, side: int, move: int, main_history: np.ndarray) -> int:\n    piece = abs(int(board[move_from(move)])) - 1\n    if piece < 0:\n        return 0\n    side_index = 0 if side == WHITE else 1\n    return int(main_history[side_index, piece, move_to(move)])\n\n\n@njit(cache=False, inline="always")\ndef _main_history_gravity(value: int, bonus: int) -> int:\n    if bonus > MAIN_HISTORY_LIMIT:\n        bonus = MAIN_HISTORY_LIMIT\n    elif bonus < -MAIN_HISTORY_LIMIT:\n        bonus = -MAIN_HISTORY_LIMIT\n    value = value + bonus - (value * abs(bonus)) // MAIN_HISTORY_LIMIT\n    if value > MAIN_HISTORY_LIMIT:\n        return MAIN_HISTORY_LIMIT\n    if value < -MAIN_HISTORY_LIMIT:\n        return -MAIN_HISTORY_LIMIT\n    return value\n\n\n@njit(cache=False, inline="always")\ndef _update_main_history(main_history: np.ndarray, side: int, piece: int, to_square: int, bonus: int) -> None:\n    side_index = 0 if side == WHITE else 1\n    main_history[side_index, piece, to_square] = _main_history_gravity(\n        int(main_history[side_index, piece, to_square]), bonus\n    )\n\n\n@njit(cache=False, inline="always")\ndef _main_history_bonus(depth: int) -> int:\n    return min(2_400, 80 * depth * depth + 100 * depth)\n\n\n@njit(cache=False)\ndef _order_moves_with_killers(\n    board: np.ndarray,\n    side: int,\n    moves: np.ndarray,\n    count: int,\n    preferred: int,\n    scores: np.ndarray,\n    killer0: int,\n    killer1: int,\n    main_history: np.ndarray,\n) -> None:\n    \"\"\"Order PV/tacticals, killers, then compact learned quiet history.\"\"\"\n    for index in range(count):\n        move = int(moves[index])\n        score = _move_order_score(board, move, preferred)\n        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n            elif not _is_tactical(board, move):\n                score += _main_history_value(board, side, move, main_history)\n        scores[index] = score\n'''
rep(old, new, 1, "order function")

rep(
    '''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, bool]:''',
    '''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n    main_history: np.ndarray,\n) -> tuple[int, bool]:''',
    1,
    "negamax signature",
)
rep(
    '''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n) -> tuple[int, int, bool]:''',
    '''    history_contexts: np.ndarray,\n    tt_table: np.ndarray,\n    main_history: np.ndarray,\n) -> tuple[int, int, bool]:''',
    1,
    "root signature",
)

rep(
    '''    _order_moves_with_killers(\n        board,\n        moves,\n        count,\n        preferred,\n        score_stack[ply],\n        int(killers[ply, 0]),\n        int(killers[ply, 1]),\n    )''',
    '''    _order_moves_with_killers(\n        board,\n        side,\n        moves,\n        count,\n        preferred,\n        score_stack[ply],\n        int(killers[ply, 0]),\n        int(killers[ply, 1]),\n        main_history,\n    )''',
    1,
    "order call",
)

rep(
    '''        quiet = not _is_tactical(board, move)\n        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)''',
    '''        quiet = not _is_tactical(board, move)\n        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])\n        history_piece = abs(int(board[move_from(move)])) - 1 if quiet else -1\n        quiet_history = _main_history_value(board, side, move, main_history) if quiet else 0\n        child_halfmove = _next_halfmove_clock(board, move, halfmove_clock)''',
    1,
    "quiet block",
)

rep(
    '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0''',
    '''        lmr_candidate = not checked and quiet and not protected_killer\n        reduction = _lmr_v3_reduction(depth, index) if lmr_candidate else 0\n        if MAIN_HISTORY_USE_LMR and reduction > 0 and quiet_history >= MAIN_HISTORY_GOOD:\n            reduction -= 1''',
    1,
    "LMR block",
)

# Four recursive calls inside _negamax use this exact tail.
rep(
    '''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,\n            )''',
    '''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table, main_history,\n            )''',
    4,
    "recursive negamax tails",
)

rep(
    '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if score > best_score:\n''',
    '''        undo_move_inplace(board, side, move, captured_piece, captured_square)\n        if quiet and beta == alpha_original + 1 and history_piece >= 0:\n            bonus = _main_history_bonus(depth)\n            if score < beta:\n                bonus = -(bonus // 2)\n            _update_main_history(main_history, side, history_piece, move_to(move), bonus)\n        if score > best_score:\n''',
    1,
    "history training",
)

# Root has three child _negamax calls with the same compact tail.
remaining = '''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,\n            )'''
count = s.count(remaining)
if count != 3:
    raise SystemExit(f"root negamax tail count={count} expected=3")
s = s.replace(
    remaining,
    '''                path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table, main_history,\n            )''',
    count,
)

# One tiny table lives for the whole iterative-deepening call, preserving information between depths.
alloc_anchor = '''    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)\n'''
if s.count(alloc_anchor) != 3:
    raise SystemExit(f"killers allocation count={s.count(alloc_anchor)} expected=3")
s = s.replace(
    alloc_anchor,
    alloc_anchor + '''    main_history = np.zeros((2, 6, 64), dtype=np.int16)\n''',
)

rep(
    '''            history_contexts,\n            tt_table,\n        )''',
    '''            history_contexts,\n            tt_table,\n            main_history,\n        )''',
    1,
    "stateful root tail",
)
rep(
    '''            killers, hash_keys, hash_moves, history_contexts,\n            tt_table,\n        )''',
    '''            killers, hash_keys, hash_moves, history_contexts,\n            tt_table, main_history,\n        )''',
    2,
    "adaptive/timed root tails",
)

p.write_text(s)
print(f"patched compact history mode={mode} path={p}")
