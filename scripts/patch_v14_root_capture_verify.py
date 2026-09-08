#!/usr/bin/env python3
"""Extend only tactically forcing high-value captures by one ply at the root.

The extension is deliberately narrow: captures of a rook/queen, en-passant, or captures where the
victim is at least as valuable as the attacker. It is root-only, never changes move membership,
qsearch, LMR or pruning, and is intended to test V13's exact-capture weakness without SEE's hot-path
cost.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count=source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old,new,1)


def patch(path: Path) -> None:
    source=path.read_text()
    if "_root_high_value_capture_verify" in source:
        raise SystemExit("patch already applied")

    anchor='''@njit(cache=False)\ndef _root(\n'''
    helper='''@njit(cache=False, inline="always")
def _root_high_value_capture_verify(board: np.ndarray, move: int) -> bool:
    to_square = move_to(move)
    victim = 0
    if move & FLAG_EP:
        victim = PAWN
    else:
        signed_victim = int(board[to_square])
        if signed_victim != EMPTY:
            victim = abs(signed_victim)
    if victim == 0:
        return False
    if victim >= ROOK:
        return True
    attacker = abs(int(board[move_from(move)]))
    return int(PIECE_VALUE[victim]) >= int(PIECE_VALUE[attacker])


@njit(cache=False)
def _root(
'''
    source=replace_once(source,anchor,helper,"helper insertion")

    old='''        child_depth = depth - 1
        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:
            # Root preferred moves live in the 10M ordering band, so classify the rare horizon case
            # directly rather than inferring it from order_score.
            child_depth = depth
'''
    new='''        child_depth = depth - 1
        if depth == 1 and _quiet_pawn_relative_rank(board, move) == 6:
            # Root preferred moves live in the 10M ordering band, so classify the rare horizon case
            # directly rather than inferring it from order_score.
            child_depth = depth
        elif depth >= 3 and _root_high_value_capture_verify(board, move):
            # Verify rare, materially forcing root captures one ply deeper. This is deliberately not
            # a general capture extension: only high-value/equal-or-better exchanges qualify.
            child_depth = depth
'''
    source=replace_once(source,old,new,"root depth")
    path.write_text(source)


def main() -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path',type=Path)
    args=parser.parse_args();patch(args.path);return 0

if __name__=='__main__':
    raise SystemExit(main())
