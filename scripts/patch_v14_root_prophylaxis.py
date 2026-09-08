#!/usr/bin/env python3
"""Add a root-only defensive/prophylaxis danger verifier to exact V13.

The candidate deliberately does *not* change recursive evaluation. After a completed root child has
been searched, it measures cheap opponent counterplay in that resulting position: immediate legal
checks, heavy-piece checking access, own king shield, open king rays, and enemy rook penetration.
Only modestly favourable root moves are penalised, matching the rated-game attack->consolidate
failure mode while leaving losing counterplay and interior-node tactics alone.
"""
from __future__ import annotations

import argparse
from pathlib import Path


HELPER_ANCHOR = """\n\n\n@njit(cache=False)\ndef _root(\n"""

HELPER = """

@njit(cache=False)
def _root_prophylaxis_penalty(
    board: np.ndarray,
    our_side: int,
    castling: int,
    ep_square: int,
    eval_child: np.ndarray,
    pseudo: np.ndarray,
    replies: np.ndarray,
) -> int:
    \"\"\"Cheap root-only estimate of dangerous opponent activity after our candidate move.\"\"\"
    opponent = -our_side
    own_king = int(
        eval_child[EVAL_WHITE_KING] if our_side == WHITE else eval_child[EVAL_BLACK_KING]
    )
    if own_king < 0:
        return 0

    enemy_queen = False
    enemy_rook = False
    enemy_bishop = False
    penetrating_rooks = 0
    close_penetrating_rooks = 0
    king_file = own_king & 7
    king_rank = own_king >> 3
    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece * our_side >= 0:
            continue
        kind = abs(signed_piece)
        if kind == QUEEN:
            enemy_queen = True
        elif kind == BISHOP:
            enemy_bishop = True
        elif kind == ROOK:
            enemy_rook = True
            rank = square >> 3
            penetrated = rank <= 2 if our_side == WHITE else rank >= 5
            if penetrated:
                penetrating_rooks += 1
                file = square & 7
                if abs(file - king_file) <= 3 and abs(rank - king_rank) <= 3:
                    close_penetrating_rooks += 1

    shield_pawns = 0
    for delta_rank in range(-1, 2):
        for delta_file in range(-1, 2):
            if delta_file == 0 and delta_rank == 0:
                continue
            file = king_file + delta_file
            rank = king_rank + delta_rank
            if 0 <= file < 8 and 0 <= rank < 8:
                square = rank * 8 + file
                if int(board[square]) == our_side * PAWN:
                    shield_pawns += 1

    open_slider_rays = 0
    for delta_rank in range(-1, 2):
        for delta_file in range(-1, 2):
            if delta_file == 0 and delta_rank == 0:
                continue
            diagonal = delta_file != 0 and delta_rank != 0
            relevant_slider = enemy_queen or (enemy_bishop if diagonal else enemy_rook)
            if not relevant_slider:
                continue
            file = king_file + delta_file
            rank = king_rank + delta_rank
            if 0 <= file < 8 and 0 <= rank < 8:
                square = rank * 8 + file
                if int(board[square]) == EMPTY:
                    open_slider_rays += 1

    reply_count = _legal_moves_for_state(
        board, opponent, castling, ep_square, pseudo, replies, eval_child
    )
    checks = 0
    quiet_checks = 0
    heavy_checks = 0
    for index in range(reply_count):
        reply = int(replies[index])
        tactical = _is_tactical(board, reply)
        moving_kind = abs(int(board[move_from(reply)]))
        _, _, captured, captured_square = make_move_inplace(
            board, opponent, castling, ep_square, reply
        )
        gives_check = is_square_attacked(board, own_king, opponent)
        undo_move_inplace(board, opponent, reply, captured, captured_square)
        if gives_check:
            checks += 1
            if not tactical:
                quiet_checks += 1
            if moving_kind == QUEEN or moving_kind == ROOK:
                heavy_checks += 1

    penalty = 0
    penalty += min(checks, 3) * 16
    penalty += min(quiet_checks, 2) * 12
    penalty += min(heavy_checks, 2) * 14
    penalty += penetrating_rooks * 18
    penalty += close_penetrating_rooks * 10
    penalty += min(open_slider_rays, 4) * 7
    if shield_pawns == 0:
        penalty += 14
    elif shield_pawns == 1:
        penalty += 6
    if heavy_checks > 0 and shield_pawns <= 1:
        penalty += 18
    if checks > 0 and penetrating_rooks > 0:
        penalty += 22
    if penalty > 140:
        penalty = 140
    return penalty


@njit(cache=False)
def _root(
"""

OLD_SCORE_BLOCK = """        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if aborted:
            return best_move, best_score, True
        score = -score
        if score > best_score:
"""

NEW_SCORE_BLOCK = """        if aborted:
            undo_move_inplace(board, side, move, captured_piece, captured_square)
            return best_move, best_score, True
        score = -score
        # Root-only consolidation bias. Apply only once search is non-trivial and the candidate is
        # not already losing; V13's aggressive counterplay remains untouched when behind.
        if depth >= 4 and score > 0 and score < MATE_THRESHOLD:
            danger = _root_prophylaxis_penalty(
                board, side, child_castling, child_ep, eval_stack[1],
                pseudo_stack[1], move_stack[1],
            )
            # Full prophylaxis weight in the common +0.5..+6 range. Very large winning scores get
            # half weight so a tactical conversion is not displaced by generic king neatness.
            if score > 600:
                danger = danger // 2
            score -= danger
        undo_move_inplace(board, side, move, captured_piece, captured_square)
        if score > best_score:
"""


def patch(path: Path) -> None:
    source = path.read_text()
    if source.count(HELPER_ANCHOR) != 1:
        raise SystemExit(f"root helper anchor drifted: {source.count(HELPER_ANCHOR)}")
    if source.count(OLD_SCORE_BLOCK) != 1:
        raise SystemExit(f"root score anchor drifted: {source.count(OLD_SCORE_BLOCK)}")
    source = source.replace(HELPER_ANCHOR, HELPER, 1)
    source = source.replace(OLD_SCORE_BLOCK, NEW_SCORE_BLOCK, 1)
    if source.count("_root_prophylaxis_penalty(") != 2:
        raise SystemExit("unexpected prophylaxis helper structure")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
