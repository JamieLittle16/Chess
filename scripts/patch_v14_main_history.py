#!/usr/bin/env python3
"""Patch exact qualified V13 into the first V14-A quiet-history candidate.

This experiment is intentionally narrow: add a bounded from/to quiet-history table, use it only
for ordinary-quiet move ordering, and reward quiet beta cutoffs.  It does not alter evaluation,
pruning margins, LMR reductions, legality, draw handling, qsearch, TT semantics, or time management.
"""
from __future__ import annotations

import argparse
from pathlib import Path

CONSTANT_MARKER = "MAX_PLY = MAX_DEPTH + MAX_QPLY + 4\n"
CONSTANTS = """MAX_PLY = MAX_DEPTH + MAX_QPLY + 4

# V14-A main quiet history. Keep the table deliberately small and bounded; the first experiment
# uses it only for ordering, never as a pruning or evaluation signal. A maximum ordering lift of
# 2,097,152 stays well below the quiet-killer bands (~4.9M), preserving the proven tactical/killer
# hierarchy while allowing successful ordinary quiets to move materially earlier.
QUIET_HISTORY_MAX = 16_384
QUIET_HISTORY_ORDER_SCALE = 128
"""

OLD_ORDER_SIG = '''def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
) -> None:
    """Order PV/tacticals first, then two quiet killers, then ordinary quiets."""
'''
NEW_ORDER_SIG = '''def _order_moves_with_killers(
    board: np.ndarray,
    side: int,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    quiet_history: np.ndarray,
) -> None:
    """Order PV/tacticals, killers, then ordinary quiets by learned cutoff history."""
'''

OLD_ORDER_BODY = '''        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
        scores[index] = score
'''
NEW_ORDER_BODY = '''        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            else:
                side_index = 0 if side == WHITE else 1
                score += int(
                    quiet_history[side_index, move_from(move), move_to(move)]
                ) * QUIET_HISTORY_ORDER_SCALE
        scores[index] = score
'''

OLD_ORDER_CALL = '''    _order_moves_with_killers(
        board,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
'''
NEW_ORDER_CALL = '''    _order_moves_with_killers(
        board,
        side,
        moves,
        count,
        preferred,
        score_stack[ply],
        int(killers[ply, 0]),
        int(killers[ply, 1]),
        quiet_history,
    )
'''

OLD_KILLER_UPDATE = '''        if alpha >= beta:
            # Preserve submission-V11 recursive killer semantics; promotion verification is root-only.
            if order_score < 5_590_000:
                current = int(killers[ply, 0])
                if move != current:
                    killers[ply, 1] = current
                    killers[ply, 0] = move
            best_move = move
            break
'''
NEW_KILLER_UPDATE = '''        if alpha >= beta:
            # V14-A: reward only an actual quiet beta-cutoff. Use a gravity-style bounded update so
            # repeated cutoffs saturate smoothly and stale history cannot grow without limit. This
            # is intentionally ordering-only; LMR/pruning do not consume history in this experiment.
            if quiet:
                side_index = 0 if side == WHITE else 1
                from_square = move_from(move)
                to_square = move_to(move)
                bonus = min(2_048, 32 * depth * depth)
                old_history = int(quiet_history[side_index, from_square, to_square])
                quiet_history[side_index, from_square, to_square] = old_history + bonus - (
                    old_history * bonus // QUIET_HISTORY_MAX
                )
            # Preserve submission-V11 recursive killer semantics; promotion verification is root-only.
            if order_score < 5_590_000:
                current = int(killers[ply, 0])
                if move != current:
                    killers[ply, 1] = current
                    killers[ply, 0] = move
            best_move = move
            break
'''


def replace_exact(source: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} occurrence(s), found {count}")
    return source.replace(old, new)


def patch(path: Path) -> None:
    source = path.read_text()
    if "QUIET_HISTORY_MAX" in source:
        raise SystemExit("source already contains V14-A quiet history")

    source = replace_exact(source, CONSTANT_MARKER, CONSTANTS, "constants")
    source = replace_exact(source, OLD_ORDER_SIG, NEW_ORDER_SIG, "order signature")
    source = replace_exact(source, OLD_ORDER_BODY, NEW_ORDER_BODY, "order body")
    source = replace_exact(source, OLD_ORDER_CALL, NEW_ORDER_CALL, "order call")
    source = replace_exact(source, OLD_KILLER_UPDATE, NEW_KILLER_UPDATE, "cutoff update")

    signature_token = "    path_keys: np.ndarray,\n    killers: np.ndarray,\n    hash_keys: np.ndarray,\n"
    signature_replacement = (
        "    path_keys: np.ndarray,\n    killers: np.ndarray,\n"
        "    quiet_history: np.ndarray,\n    hash_keys: np.ndarray,\n"
    )
    source = replace_exact(source, signature_token, signature_replacement, "search signatures", 2)

    call_token = "path_keys, killers, hash_keys, hash_moves, history_contexts, tt_table,"
    call_replacement = "path_keys, killers, quiet_history, hash_keys, hash_moves, history_contexts, tt_table,"
    call_count = source.count(call_token)
    if call_count < 5:
        raise SystemExit(f"recursive/root calls: suspiciously low occurrence count {call_count}")
    source = source.replace(call_token, call_replacement)

    # Exact V13 allocates fresh per-search killers in three public entrypoints. Keep history local to
    # one search call for this first experiment, avoiding cross-game leakage or new persistent state.
    allocation = "    killers = np.full((MAX_PLY, 2), -1, dtype=np.int32)\n"
    replacement = allocation + "    quiet_history = np.zeros((2, 64, 64), dtype=np.int32)\n"
    allocation_count = source.count(allocation)
    if allocation_count != 3:
        raise SystemExit(f"quiet-history allocation: expected 3 sites, found {allocation_count}")
    source = source.replace(allocation, replacement)

    multiline = "            killers,\n            hash_keys,\n"
    multiline_replacement = "            killers,\n            quiet_history,\n            hash_keys,\n"
    multiline_count = source.count(multiline)
    if multiline_count:
        source = source.replace(multiline, multiline_replacement)

    compact_root = "            killers, hash_keys, hash_moves, history_contexts,\n"
    compact_root_replacement = (
        "            killers, quiet_history, hash_keys, hash_moves, history_contexts,\n"
    )
    compact_root_count = source.count(compact_root)
    if compact_root_count != 2:
        raise SystemExit(
            f"compact root calls: expected 2 sites, found {compact_root_count}"
        )
    source = source.replace(compact_root, compact_root_replacement)

    if source.count("def _lmr_v3_reduction") != 1 or source.count("def _quiescence(") != 1:
        raise SystemExit("unexpected search structure after patch")
    if "correction = correction // 6" not in source:
        raise SystemExit("qualified V13 1/6 residual baseline is missing")

    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
