#!/usr/bin/env python3
"""Add conservative depth-1/2 LMP conditioned by cheap improving and quiet history.

This is deliberately narrower than the old raw LMP experiment: only scout/non-check nodes that
already qualify for PUNCH133's shallow pruning machinery participate; killers/checks and strong-
history quiets escape; improving nodes prune later. No new recursive state or neural eval is added.
"""
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

    old = """        if pruning_static_eval - 120 * depth >= beta:
            return pruning_static_eval, False

    # V18 adaptive verified-null seed: conservative R2 null-move pruning on scout nodes only.
"""
    new = """        if pruning_static_eval - 120 * depth >= beta:
            return pruning_static_eval, False

    # V18 conditioned-LMP signal.  The classical state is already maintained incrementally for
    # every ply, so comparing the same side with two plies ago needs no H64 materialisation and no
    # additional recursive state.  Restrict it to exactly the shallow scout nodes where LMP may act.
    improving = False
    if pruning_static_eval != INFINITY and depth <= 2 and ply >= 2:
        current_prune_eval = _evaluate_state_classical(side, eval_stack[ply])
        previous_prune_eval = _evaluate_state_classical(side, eval_stack[ply - 2])
        improving = current_prune_eval > previous_prune_eval

    # V18 adaptive verified-null seed: conservative R2 null-move pruning on scout nodes only.
"""
    rep(old, new)

    old = """        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )
        # Check status only matters when this quiet could actually be reduced or pruned. Avoiding
        # the attack test for early/non-reduced quiets preserves exact search semantics while
        # removing work from one of the hottest recursive paths.
        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate)
        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False
        # Accepted Rust late-quiet futility on top of submission-V11 recursive semantics. The shared
        # static eval exists only on the same conservative scout
        # nodes as RFP. We have already made the move so gives_check is exact; skipped moves are
        # immediately unmade and never enter TT/killer state.
        if futility_candidate and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue
"""
    new = """        futility_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= 4
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and pruning_static_eval + 180 * depth <= alpha
        )
        # Raw LMP at roughly 5/9 moves was Elo/node-positive but clock-neutral in V15.  Make it
        # deliberately more selective here: depth 1 starts at the 7th ordered move, depth 2 at the
        # 11th; improving positions get two extra moves, strongly bad history one fewer, and strong
        # positive history escapes entirely.  `index` is zero-based.
        lmp_limit = 6 if depth <= 1 else 10
        if improving:
            lmp_limit += 2
        if move_history_score <= -QUIET_HISTORY_LMR_THRESHOLD:
            lmp_limit -= 1
        history_lmp_candidate = (
            pruning_static_eval != INFINITY
            and depth <= 2
            and index >= lmp_limit
            and quiet
            and not protected_killer
            and abs(alpha) < MATE_THRESHOLD
            and move_history_score < QUIET_HISTORY_LMR_THRESHOLD
        )
        # Check status only matters when this quiet could actually be reduced or pruned. Avoiding
        # the attack test for early/non-reduced quiets preserves exact search semantics while
        # removing work from one of the hottest recursive paths.
        need_gives_check = lmr_candidate and (reduction > 0 or futility_candidate or history_lmp_candidate)
        gives_check = _state_in_check(board, -side, eval_stack[ply + 1]) if need_gives_check else False
        # Both shallow filters use `continue`, never `break`: a future SEE-staged build may place
        # losing captures after quiets, and those tactical moves must remain searchable.
        if (futility_candidate or history_lmp_candidate) and not gives_check:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            continue
"""
    rep(old, new)

    p.write_text(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
