#!/usr/bin/env python3
"""Patch exact V13 with a compact side/from/to quiet history heuristic.

History storage is appended to the existing hash-move int32 buffer so recursive search signatures
remain unchanged. The first HASH_MOVE_SIZE entries retain their exact previous meaning.
"""
from __future__ import annotations
import argparse
from pathlib import Path


def once(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1:
        raise SystemExit(f'{label} anchor count={n}')
    return s.replace(old,new,1)


def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('path',type=Path)
    ap.add_argument('--score-scale',type=int,default=128)
    ap.add_argument('--bonus-scale',type=int,default=16)
    args=ap.parse_args()
    if args.score_scale<=0 or args.bonus_scale<=0:
        raise SystemExit('scales must be positive')
    p=args.path; s=p.read_text()

    anchor='HASH_MOVE_MASK = HASH_MOVE_SIZE - 1\n'
    constants=(anchor+
        'HISTORY_SIZE = 2 * 64 * 64\n'
        'HISTORY_OFFSET = HASH_MOVE_SIZE\n'
        'HASH_MOVE_STORAGE_SIZE = HASH_MOVE_SIZE + HISTORY_SIZE\n'
        'HISTORY_MAX = 16384\n'
        f'HISTORY_SCORE_SCALE = {args.score_scale}\n'
        f'HISTORY_BONUS_SCALE = {args.bonus_scale}\n')
    s=once(s,anchor,constants,'history constants')

    # All internal search-local hash-move allocations gain the appended history region. Hash keys
    # remain exactly HASH_MOVE_SIZE because only the move array carries the history scores.
    n=s.count('np.full(HASH_MOVE_SIZE, -1, dtype=np.int32)')
    if n<1:
        raise SystemExit('hash move allocation anchor missing')
    s=s.replace('np.full(HASH_MOVE_SIZE, -1, dtype=np.int32)',
                'np.full(HASH_MOVE_STORAGE_SIZE, -1, dtype=np.int32)')

    old='''def _order_moves_with_killers(
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
'''
    new='''def _order_moves_with_killers(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    killer0: int,
    killer1: int,
    side: int,
    history_moves: np.ndarray,
) -> None:
    """Order PV/tacticals, killers, then quiets by learned cutoff history."""
    side_offset = 0 if side == WHITE else 4096
    for index in range(count):
        move = int(moves[index])
        score = _move_order_score(board, move, preferred)
        if score < 5_040_000:
            if move == killer0:
                score += 5_000_000
            elif move == killer1:
                score += 4_900_000
            else:
                hist_index = HISTORY_OFFSET + side_offset + move_from(move) * 64 + move_to(move)
                history_score = int(history_moves[hist_index])
                if history_score == -1:
                    history_score = 0
                score += history_score * HISTORY_SCORE_SCALE
        scores[index] = score
'''
    s=once(s,old,new,'order function')

    old_call='''        int(killers[ply, 0]),
        int(killers[ply, 1]),
    )
'''
    new_call='''        int(killers[ply, 0]),
        int(killers[ply, 1]),
        side,
        hash_moves,
    )
'''
    # This exact suffix occurs only at the recursive killer-order call.
    s=once(s,old_call,new_call,'order call')

    cutoff='''        if alpha >= beta:
            # Preserve submission-V11 recursive killer semantics; promotion verification is root-only.
            if order_score < 5_590_000:
                current = int(killers[ply, 0])
                if move != current:
                    killers[ply, 1] = current
                    killers[ply, 0] = move
            best_move = move
            break
'''
    cutoff_new='''        if alpha >= beta:
            # Preserve killer semantics, and reinforce quiets that actually caused a beta cutoff.
            # Gravity-style bounded updates prevent one early event from permanently dominating.
            if quiet:
                side_offset = 0 if side == WHITE else 4096
                hist_index = HISTORY_OFFSET + side_offset + move_from(move) * 64 + move_to(move)
                hist = int(hash_moves[hist_index])
                if hist == -1:
                    hist = 0
                bonus = depth * depth * HISTORY_BONUS_SCALE
                if bonus > HISTORY_MAX:
                    bonus = HISTORY_MAX
                hist += bonus - (hist * bonus) // HISTORY_MAX
                if hist > HISTORY_MAX:
                    hist = HISTORY_MAX
                hash_moves[hist_index] = hist

                # Mildly demote earlier quiets that failed to cut off at the same node. This is the
                # standard complementary signal and materially improves ordering convergence.
                malus = bonus // 2
                for prior_index in range(index):
                    prior_move = int(moves[prior_index])
                    if _is_tactical(board, prior_move):
                        continue
                    prior_hist_index = (
                        HISTORY_OFFSET + side_offset
                        + move_from(prior_move) * 64 + move_to(prior_move)
                    )
                    prior_hist = int(hash_moves[prior_hist_index])
                    if prior_hist == -1:
                        prior_hist = 0
                    prior_hist -= malus + (prior_hist * malus) // HISTORY_MAX
                    if prior_hist < -HISTORY_MAX:
                        prior_hist = -HISTORY_MAX
                    hash_moves[prior_hist_index] = prior_hist

            if order_score < 5_590_000:
                current = int(killers[ply, 0])
                if move != current:
                    killers[ply, 1] = current
                    killers[ply, 0] = move
            best_move = move
            break
'''
    s=once(s,cutoff,cutoff_new,'cutoff update')

    p.write_text(s)
    return 0

if __name__=='__main__':
    raise SystemExit(main())
