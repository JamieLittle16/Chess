#!/usr/bin/env python3
"""Add a conservative capture-history ordering signal to exact final V13.

The candidate never prunes or extends a move. It records only successful recursive capture beta
cutoffs within the current search and adds a bounded bonus to later captures with the same
(piece, destination, captured-piece) context. V13's evaluation, qsearch membership, LMR, pruning,
TT score semantics and legality core remain unchanged.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()

    source = replace_once(
        source,
        """TT_GENERATION_INDEX = TT_SIZE * 3
TT_STORAGE_SIZE = TT_GENERATION_INDEX + 1
""",
        """TT_GENERATION_INDEX = TT_SIZE * 3
CAPTURE_HISTORY_OFFSET = TT_GENERATION_INDEX + 1
CAPTURE_HISTORY_SIZE = 12 * 64 * 6
CAPTURE_HISTORY_MAX = 4096
CAPTURE_HISTORY_ORDER_SCALE = 24
TT_STORAGE_SIZE = CAPTURE_HISTORY_OFFSET + CAPTURE_HISTORY_SIZE
""",
        "TT storage",
    )

    source = replace_once(
        source,
        '''@njit(cache=False)
def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
) -> None:
    """Order PV/tacticals first, then two quiet killers, then ordinary quiets."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
        scores[index] = score
''',
        '''@njit(cache=False, inline="always")
def _capture_history_index(board: np.ndarray, move: int) -> int:
    from_square = move_from(move)
    to_square = move_to(move)
    signed_piece = int(board[from_square])
    captured_kind = PAWN if (move & FLAG_EP) else abs(int(board[to_square]))
    if captured_kind == 0:
        return -1
    piece_index = abs(signed_piece) - 1 + (0 if signed_piece > 0 else 6)
    return CAPTURE_HISTORY_OFFSET + ((piece_index * 64 + to_square) * 6 + captured_kind - 1)


@njit(cache=False, inline="always")
def _reward_capture_history(tt_table: np.ndarray, index: int, depth: int) -> None:
    if index < 0:
        return
    current = int(tt_table[index])
    bonus = min(768, 20 * depth * depth)
    updated = current + bonus - (current * bonus // CAPTURE_HISTORY_MAX)
    if updated > CAPTURE_HISTORY_MAX:
        updated = CAPTURE_HISTORY_MAX
    tt_table[index] = np.uint64(updated)


@njit(cache=False)
def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    tt_table: np.ndarray,
) -> None:
    """Order PV/tacticals first, then two quiet killers, then ordinary quiets."""
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        capture_index = _capture_history_index(board, move)
        if capture_index >= 0 and move != preferred:
            score += int(tt_table[capture_index]) * CAPTURE_HISTORY_ORDER_SCALE
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
        scores[index] = score
''',
        "capture-history ordering",
    )

    source = replace_once(
        source,
        """        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
""",
        """        int(killers[ply, 0]),
        int(killers[ply, 1]),
        tt_table,
    )
""",
        "ordering call",
    )

    source = replace_once(
        source,
        """        quiet = not _is_tactical(board, move)
        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
""",
        """        quiet = not _is_tactical(board, move)
        capture_history_index = _capture_history_index(board, move)
        protected_killer = move == int(killers[ply, 0]) or move == int(killers[ply, 1])
""",
        "cutoff capture context",
    )

    source = replace_once(
        source,
        """        if alpha >= beta:
            # Preserve submission-V11 recursive killer semantics; promotion verification is root-only.
            if order_score < 5_590_000:
""",
        """        if alpha >= beta:
            if capture_history_index >= 0:
                _reward_capture_history(tt_table, capture_history_index, depth)
            # Preserve submission-V11 recursive killer semantics; promotion verification is root-only.
            if order_score < 5_590_000:
""",
        "capture cutoff reward",
    )

    # The timed-cached entry reuses the TT across our moves. Keep this first experiment strictly
    # per-search by clearing only the small capture-history tail while preserving TT generations.
    source = replace_once(
        source,
        """    history_contexts = np.empty(MAX_PLY, dtype=np.uint64)
    history_contexts[0] = _root_history_context(history_keys, history_count)
    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
    _build_eval_state_into(board, eval_stack[0])
""",
        """    history_contexts = np.empty(MAX_PLY, dtype=np.uint64)
    history_contexts[0] = _root_history_context(history_keys, history_count)
    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)
    for capture_history_slot in range(CAPTURE_HISTORY_SIZE):
        tt_table[CAPTURE_HISTORY_OFFSET + capture_history_slot] = np.uint64(0)
    _build_eval_state_into(board, eval_stack[0])
""",
        "timed-cache history reset",
    )

    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
