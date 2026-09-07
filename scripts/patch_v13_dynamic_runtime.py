#!/usr/bin/env python3
"""Patch the exact V13 Numba evaluator with the trained compact dynamic correction.

The dynamic model was trained on half-strength original V13 linear residual plus sixteen interaction
features.  This patcher preserves that training contract exactly and exposes qply/scale knobs so the
arena can measure the strength/throughput frontier without changing the search architecture.
"""
from __future__ import annotations

import argparse
from pathlib import Path

DYNAMIC_CODE = r'''

DYNAMIC_Q = 16
DYNAMIC_CLAMP_Q = 300 * DYNAMIC_Q
DYNAMIC_BIAS_Q = 585
DYNAMIC_WEIGHTS_Q = np.array(
    (93, 107, 80, -27, 607, 296, 488, 467, 509, 92, 935, 232, 38, 75, 646, 399),
    dtype=np.int16,
)


@njit(cache=False, inline="always")
def _dynamic_in_king_zone(square: int, king_square_value: int) -> bool:
    if king_square_value < 0:
        return False
    file_delta = (square & 7) - (king_square_value & 7)
    if file_delta < 0:
        file_delta = -file_delta
    rank_delta = (square >> 3) - (king_square_value >> 3)
    if rank_delta < 0:
        rank_delta = -rank_delta
    return file_delta <= 1 and rank_delta <= 1


@njit(cache=False, inline="always")
def _dynamic_side_score_q(board: np.ndarray, side: int, own_king: int, enemy_king: int) -> int:
    # No Python objects enter this routine.  The tiny fixed-board rebuild is intentionally gated by
    # qply at the caller so we can buy interaction accuracy only where it earns search strength.
    pawn_files = np.zeros(16, dtype=np.int16)
    for square in range(64):
        signed_piece = int(board[square])
        if abs(signed_piece) == PAWN:
            index = square & 7
            if signed_piece < 0:
                index += 8
            pawn_files[index] += 1

    own_offset = 0 if side == WHITE else 8
    enemy_offset = 8 if side == WHITE else 0

    rook_mobility = 0
    bishop_mobility = 0
    knight_mobility = 0
    queen_mobility = 0
    rook_open_files = 0
    rook_semi_open_files = 0
    rook_seventh = 0
    rook_advanced = 0
    connected_rook_hits = 0
    rook_king_zone_attacks = 0
    queen_king_zone_attacks = 0
    passed_pawns = 0

    for square in range(64):
        signed_piece = int(board[square])
        if signed_piece * side <= 0:
            continue
        piece = abs(signed_piece)
        file = square & 7
        rank = square >> 3

        if piece == KNIGHT:
            # python-chess Board.attacks() for a knight is its occupancy-independent attack mask.
            knight_mobility += int(KNIGHT_TARGET_COUNTS[square])
            continue

        if piece == ROOK or piece == QUEEN:
            for delta_file, delta_rank in ROOK_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while 0 <= target_file < 8 and 0 <= target_rank < 8:
                    target = target_rank * 8 + target_file
                    if piece == ROOK:
                        rook_mobility += 1
                        if _dynamic_in_king_zone(target, enemy_king):
                            rook_king_zone_attacks += 1
                    else:
                        queen_mobility += 1
                        if _dynamic_in_king_zone(target, enemy_king):
                            queen_king_zone_attacks += 1
                    blocker = int(board[target])
                    if blocker != EMPTY:
                        # Slider attack masks include the first blocker.  Each connected rook pair
                        # is therefore observed from both ends and divided by two below.
                        if piece == ROOK and blocker == side * ROOK:
                            connected_rook_hits += 1
                        break
                    target_file += delta_file
                    target_rank += delta_rank

        if piece == BISHOP or piece == QUEEN:
            for delta_file, delta_rank in BISHOP_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while 0 <= target_file < 8 and 0 <= target_rank < 8:
                    target = target_rank * 8 + target_file
                    if piece == BISHOP:
                        bishop_mobility += 1
                    else:
                        queen_mobility += 1
                        if _dynamic_in_king_zone(target, enemy_king):
                            queen_king_zone_attacks += 1
                    if int(board[target]) != EMPTY:
                        break
                    target_file += delta_file
                    target_rank += delta_rank

        if piece == ROOK:
            own_pawns = int(pawn_files[own_offset + file])
            enemy_pawns = int(pawn_files[enemy_offset + file])
            if own_pawns == 0 and enemy_pawns == 0:
                rook_open_files += 1
            elif own_pawns == 0:
                rook_semi_open_files += 1
            relative_rank = rank if side == WHITE else 7 - rank
            if relative_rank == 6:
                rook_seventh += 1
            if relative_rank >= 4:
                rook_advanced += 1

        if piece == PAWN:
            passed = True
            for enemy_file in range(max(0, file - 1), min(7, file + 1) + 1):
                if int(pawn_files[enemy_offset + enemy_file]) == 0:
                    continue
                for target_rank in range(8):
                    target = target_rank * 8 + enemy_file
                    if int(board[target]) != -side * PAWN:
                        continue
                    if (side == WHITE and target_rank > rank) or (side != WHITE and target_rank < rank):
                        passed = False
                        break
                if not passed:
                    break
            if passed:
                passed_pawns += 1

    connected_rooks = connected_rook_hits // 2

    king_shield = 0
    king_closed_files = 0
    if own_king >= 0:
        king_file = own_king & 7
        king_rank = own_king >> 3
        direction = 1 if side == WHITE else -1
        for file in range(max(0, king_file - 1), min(7, king_file + 1) + 1):
            if int(pawn_files[own_offset + file]) > 0:
                king_closed_files += 1
            for distance in (1, 2):
                rank = king_rank + direction * distance
                if 0 <= rank < 8 and int(board[rank * 8 + file]) == side * PAWN:
                    king_shield += 1

    isolated_pawns = 0
    doubled_pawns = 0
    for file in range(8):
        count = int(pawn_files[own_offset + file])
        if count == 0:
            continue
        left_empty = file == 0 or int(pawn_files[own_offset + file - 1]) == 0
        right_empty = file == 7 or int(pawn_files[own_offset + file + 1]) == 0
        if left_empty and right_empty:
            isolated_pawns += count
        if count > 1:
            doubled_pawns += count - 1

    return (
        int(DYNAMIC_WEIGHTS_Q[0]) * rook_mobility
        + int(DYNAMIC_WEIGHTS_Q[1]) * bishop_mobility
        + int(DYNAMIC_WEIGHTS_Q[2]) * knight_mobility
        + int(DYNAMIC_WEIGHTS_Q[3]) * queen_mobility
        + int(DYNAMIC_WEIGHTS_Q[4]) * rook_open_files
        + int(DYNAMIC_WEIGHTS_Q[5]) * rook_semi_open_files
        + int(DYNAMIC_WEIGHTS_Q[6]) * rook_seventh
        + int(DYNAMIC_WEIGHTS_Q[7]) * rook_advanced
        + int(DYNAMIC_WEIGHTS_Q[8]) * connected_rooks
        + int(DYNAMIC_WEIGHTS_Q[9]) * rook_king_zone_attacks
        + int(DYNAMIC_WEIGHTS_Q[10]) * queen_king_zone_attacks
        + int(DYNAMIC_WEIGHTS_Q[11]) * king_shield
        + int(DYNAMIC_WEIGHTS_Q[12]) * king_closed_files
        - int(DYNAMIC_WEIGHTS_Q[13]) * isolated_pawns
        - int(DYNAMIC_WEIGHTS_Q[14]) * doubled_pawns
        + int(DYNAMIC_WEIGHTS_Q[15]) * passed_pawns
    )


@njit(cache=False, inline="never")
def _dynamic_correction_q(board: np.ndarray, side: int, state: np.ndarray) -> int:
    white_king = int(state[EVAL_WHITE_KING])
    black_king = int(state[EVAL_BLACK_KING])
    if side == WHITE:
        us = _dynamic_side_score_q(board, WHITE, white_king, black_king)
        them = _dynamic_side_score_q(board, -WHITE, black_king, white_king)
    else:
        us = _dynamic_side_score_q(board, -WHITE, black_king, white_king)
        them = _dynamic_side_score_q(board, WHITE, white_king, black_king)
    correction_q = DYNAMIC_BIAS_Q + us - them
    if correction_q > DYNAMIC_CLAMP_Q:
        correction_q = DYNAMIC_CLAMP_Q
    elif correction_q < -DYNAMIC_CLAMP_Q:
        correction_q = -DYNAMIC_CLAMP_Q
    return correction_q


@njit(cache=False, inline="always")
def _dynamic_correction(board: np.ndarray, side: int, state: np.ndarray) -> int:
    correction_q = _dynamic_correction_q(board, side, state)
    correction_q = (correction_q * DYNAMIC_SCALE_NUM) // DYNAMIC_SCALE_DEN
    return correction_q // DYNAMIC_Q
'''


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--qply-max", type=int, default=0)
    parser.add_argument("--dynamic-scale-num", type=int, default=1)
    parser.add_argument("--dynamic-scale-den", type=int, default=1)
    return parser.parse_args()


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return source.replace(old, new, 1)


def main() -> int:
    args = parse_args()
    if args.dynamic_scale_den <= 0 or args.dynamic_scale_num < 0:
        raise SystemExit("invalid dynamic scale")
    source = args.path.read_text()

    source = replace_once(source, "    BISHOP,\n    EMPTY,", "    BISHOP,\n    BISHOP_DIRS,\n    EMPTY,", "BISHOP import")
    source = replace_once(source, "    KNIGHT,\n    MAX_MOVES,", "    KNIGHT,\n    KNIGHT_TARGET_COUNTS,\n    MAX_MOVES,", "KNIGHT import")
    source = replace_once(source, "    QUEEN,\n    ROOK,", "    QUEEN,\n    ROOK,\n    ROOK_DIRS,", "ROOK import")

    anchor = "RESIDUAL_CLAMP = 600\n"
    constants = (
        anchor
        + "RESIDUAL_SCALE_NUM = 1\nRESIDUAL_SCALE_DEN = 2\n"
        + f"DYNAMIC_QPLY_MAX = {args.qply_max}\n"
        + f"DYNAMIC_SCALE_NUM = {args.dynamic_scale_num}\n"
        + f"DYNAMIC_SCALE_DEN = {args.dynamic_scale_den}\n"
    )
    source = replace_once(source, anchor, constants, "residual constants")

    old = '    return score + correction\n\n\n@njit(cache=False, inline="never")\ndef _advance_residual_state_into('
    new = (
        "    correction = (correction * RESIDUAL_SCALE_NUM) // RESIDUAL_SCALE_DEN\n"
        "    return score + correction\n"
        + DYNAMIC_CODE
        + '\n\n@njit(cache=False, inline="never")\ndef _advance_residual_state_into('
    )
    source = replace_once(source, old, new, "evaluate insertion")

    old = "        stand_pat = _evaluate_state(side, eval_stack[ply])\n"
    new = (
        "        stand_pat = _evaluate_state(side, eval_stack[ply])\n"
        "        if qply <= DYNAMIC_QPLY_MAX:\n"
        "            stand_pat += _dynamic_correction(board, side, eval_stack[ply])\n"
    )
    source = replace_once(source, old, new, "quiescence standpat")

    old = "                fallback_score = -_evaluate_state(-side, eval_stack[1])\n"
    count = source.count(old)
    if count != 3:
        raise SystemExit(f"fallback anchor count={count}")
    source = source.replace(
        old,
        "                fallback_score = -(\n"
        "                    _evaluate_state(-side, eval_stack[1])\n"
        "                    + _dynamic_correction(board, -side, eval_stack[1])\n"
        "                )\n",
    )

    args.path.write_text(source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
