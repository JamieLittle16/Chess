#!/usr/bin/env python3
"""Add a compact learned capture-history table inside the existing history storage."""
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
        "QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES\nQUIET_HISTORY_STORAGE_SIZE = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES\nQUIET_HISTORY_LIMIT = 16_384\nQUIET_HISTORY_MAX_UPDATE = 2_048\n",
        "QUIET_HISTORY_CONT_OFFSET = QUIET_HISTORY_MAIN_ENTRIES\nCAPTURE_HISTORY_OFFSET = QUIET_HISTORY_MAIN_ENTRIES + QUIET_HISTORY_CONT_ENTRIES\nCAPTURE_HISTORY_ENTRIES = 6 * 64 * 7\nQUIET_HISTORY_STORAGE_SIZE = CAPTURE_HISTORY_OFFSET + CAPTURE_HISTORY_ENTRIES\nQUIET_HISTORY_LIMIT = 16_384\nQUIET_HISTORY_MAX_UPDATE = 2_048\nCAPTURE_HISTORY_LIMIT = 16_384\nCAPTURE_HISTORY_MAX_UPDATE = 2_048\n",
    )

    anchor = "@njit(cache=False)\ndef _quiet_history_context(board: np.ndarray, move: int) -> int:\n"
    helpers = r'''@njit(cache=False)
def _capture_history_index(board: np.ndarray, move: int) -> int:
    attacker = abs(int(board[move_from(move)]))
    target = PAWN if (move & FLAG_EP) else abs(int(board[move_to(move)]))
    if attacker <= 0 or target <= 0:
        return -1
    return CAPTURE_HISTORY_OFFSET + ((attacker - 1) * 64 + move_to(move)) * 7 + target


@njit(cache=False)
def _capture_history_update(index: int, requested_bonus: int, table: np.ndarray) -> None:
    if index < 0:
        return
    bonus = max(-CAPTURE_HISTORY_MAX_UPDATE, min(CAPTURE_HISTORY_MAX_UPDATE, requested_bonus))
    current = int(table[index])
    gravity = trunc_div_scalar(current * abs(bonus), CAPTURE_HISTORY_LIMIT)
    table[index] = np.int16(max(-CAPTURE_HISTORY_LIMIT, min(CAPTURE_HISTORY_LIMIT, current + bonus - gravity)))


'''
    rep(anchor, helpers + anchor)

    rep(
        "        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n            elif (meta & 2) == 0:\n                context = _quiet_history_context(board, move)\n                score += _quiet_history_score(side, previous_context, context, quiet_history)\n",
        "        if move != preferred and (meta & 2) != 0:\n            capture_index = _capture_history_index(board, move)\n            if capture_index >= 0:\n                score += int(quiet_history[capture_index])\n        if score < 5_040_000:\n            if move == killer0:\n                score += 5_000_000\n            elif move == killer1:\n                score += 4_900_000\n            elif (meta & 2) == 0:\n                context = _quiet_history_context(board, move)\n                score += _quiet_history_score(side, previous_context, context, quiet_history)\n",
    )

    rep(
        "        move_history_score = (\n            _quiet_history_score(side, previous_move_context, current_move_context, quiet_history)\n            if quiet else 0\n        )\n",
        "        move_history_score = (\n            _quiet_history_score(side, previous_move_context, current_move_context, quiet_history)\n            if quiet else 0\n        )\n        capture_history_index = _capture_history_index(board, move) if not quiet else -1\n",
    )

    rep(
        "        if quiet and scout_node:\n            bonus = _quiet_history_depth_bonus(depth)\n            requested = bonus if score >= beta else -(bonus // 2)\n            _quiet_history_update(\n                side, previous_move_context, current_move_context, requested, quiet_history\n            )\n",
        "        if quiet and scout_node:\n            bonus = _quiet_history_depth_bonus(depth)\n            requested = bonus if score >= beta else -(bonus // 2)\n            _quiet_history_update(\n                side, previous_move_context, current_move_context, requested, quiet_history\n            )\n        elif capture_history_index >= 0 and scout_node:\n            bonus = min(CAPTURE_HISTORY_MAX_UPDATE, 24 * depth * depth + 48 * depth)\n            requested = bonus if score >= beta else -(bonus // 4)\n            _capture_history_update(capture_history_index, requested, quiet_history)\n",
    )

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
