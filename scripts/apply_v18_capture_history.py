#!/usr/bin/env python3
"""Add compact persistent capture history on top of V18's existing history storage."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", type=Path)
    args = ap.parse_args()
    p = args.path
    s = p.read_text()

    def rep(old: str, new: str, count: int = 1) -> None:
        nonlocal s
        actual = s.count(old)
        if actual != count:
            raise RuntimeError(f"anchor count {actual} != {count}: {old[:120]!r}")
        s = s.replace(old, new, count)

    rep(
        "QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES\n"
        "QUIET_HISTORY_STORAGE_SIZE = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES\n"
        "QUIET_HISTORY_LIMIT = 16_384\n"
        "QUIET_HISTORY_MAX_UPDATE = 2_048\n"
        "QUIET_HISTORY_LMR_THRESHOLD = 4_096\n",
        "QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES\n"
        "CAPTURE_HISTORY_OFFSET = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES\n"
        "CAPTURE_HISTORY_CONTEXTS_PER_SIDE = 6 * 6 * 64\n"
        "CAPTURE_HISTORY_ENTRIES = 2 * CAPTURE_HISTORY_CONTEXTS_PER_SIDE\n"
        "QUIET_HISTORY_STORAGE_SIZE = CAPTURE_HISTORY_OFFSET + CAPTURE_HISTORY_ENTRIES\n"
        "QUIET_HISTORY_LIMIT = 16_384\n"
        "QUIET_HISTORY_MAX_UPDATE = 2_048\n"
        "QUIET_HISTORY_LMR_THRESHOLD = 4_096\n"
        "CAPTURE_HISTORY_LIMIT = 8_192\n"
        "CAPTURE_HISTORY_MAX_UPDATE = 1_024\n",
    )

    anchor = "@njit(cache=False)\ndef _history_adjusted_lmr_reduction(depth: int, move_index: int, history_score: int) -> int:\n"
    helpers = r'''@njit(cache=False)
def _capture_history_index(board: np.ndarray, move: int, side: int, captured_piece: int) -> int:
    if captured_piece == EMPTY:
        return -1
    attacker = abs(int(board[move_from(move)]))
    victim = abs(int(captured_piece))
    if attacker < PAWN or attacker > KING or victim < PAWN or victim > KING:
        return -1
    side_index = 0 if side == WHITE else 1
    return (
        CAPTURE_HISTORY_OFFSET
        + side_index * CAPTURE_HISTORY_CONTEXTS_PER_SIDE
        + (attacker - 1) * (6 * 64)
        + (victim - 1) * 64
        + move_to(move)
    )


@njit(cache=False)
def _capture_history_score(board: np.ndarray, move: int, side: int, table: np.ndarray) -> int:
    target = int(board[move_to(move)])
    if move & FLAG_EP:
        target = -side * PAWN
    index = _capture_history_index(board, move, side, target)
    return int(table[index]) if index >= 0 else 0


@njit(cache=False)
def _capture_history_depth_bonus(depth: int) -> int:
    return min(CAPTURE_HISTORY_MAX_UPDATE, 24 * depth * depth + 48 * depth)


@njit(cache=False)
def _capture_history_update(
    board: np.ndarray,
    move: int,
    side: int,
    captured_piece: int,
    requested_bonus: int,
    table: np.ndarray,
) -> None:
    index = _capture_history_index(board, move, side, captured_piece)
    if index < 0:
        return
    bonus = max(-CAPTURE_HISTORY_MAX_UPDATE, min(CAPTURE_HISTORY_MAX_UPDATE, requested_bonus))
    current_value = int(table[index])
    gravity = trunc_div_scalar(current_value * abs(bonus), CAPTURE_HISTORY_LIMIT)
    table[index] = np.int16(
        max(-CAPTURE_HISTORY_LIMIT, min(CAPTURE_HISTORY_LIMIT, current_value + bonus - gravity))
    )


'''
    rep(anchor, helpers + anchor)

    rep(
        "        score = packed >> 2\n"
        "        meta = packed & 3\n"
        "        if score < 5_040_000:\n",
        "        score = packed >> 2\n"
        "        meta = packed & 3\n"
        "        if (meta & 2) != 0:\n"
        "            score += _capture_history_score(board, move, side, quiet_history)\n"
        "        if score < 5_040_000:\n",
    )

    rep(
        "        undo_move_inplace(board, side, move, captured_piece, captured_square)\n"
        "        if quiet and scout_node:\n"
        "            bonus = _quiet_history_depth_bonus(depth)\n"
        "            requested = bonus if score >= beta else -(bonus // 2)\n"
        "            _quiet_history_update(\n"
        "                side, previous_move_context, current_move_context, requested, quiet_history\n"
        "            )\n",
        "        undo_move_inplace(board, side, move, captured_piece, captured_square)\n"
        "        if quiet and scout_node:\n"
        "            bonus = _quiet_history_depth_bonus(depth)\n"
        "            requested = bonus if score >= beta else -(bonus // 2)\n"
        "            _quiet_history_update(\n"
        "                side, previous_move_context, current_move_context, requested, quiet_history\n"
        "            )\n"
        "        elif scout_node and captured_piece != EMPTY:\n"
        "            bonus = _capture_history_depth_bonus(depth)\n"
        "            requested = bonus if score >= beta else -(bonus // 2)\n"
        "            _capture_history_update(\n"
        "                board, move, side, captured_piece, requested, quiet_history\n"
        "            )\n",
    )

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
