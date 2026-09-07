#!/usr/bin/env python3
"""Patch exact final V13 to use precomputed bishop/rook/queen ray square lists.

This candidate is deliberately semantic-neutral. It preserves the historical direction order and
near-to-far order on every ray, replacing only repeated file/rank boundary arithmetic in attack
queries, pseudo move generation, tactical pseudo move generation, and the shared legality context.
"""
from __future__ import annotations

import argparse
from pathlib import Path


TARGETS_ANCHOR = """KNIGHT_TARGETS, KNIGHT_TARGET_COUNTS = _build_fixed_targets(KNIGHT_STEPS)
KING_TARGETS, KING_TARGET_COUNTS = _build_fixed_targets(KING_STEPS)
"""

TARGETS_REPLACEMENT = """KNIGHT_TARGETS, KNIGHT_TARGET_COUNTS = _build_fixed_targets(KNIGHT_STEPS)
KING_TARGETS, KING_TARGET_COUNTS = _build_fixed_targets(KING_STEPS)


def _build_slider_rays() -> tuple[np.ndarray, np.ndarray]:
    \"\"\"Precompute slider rays in exact BISHOP_DIRS + ROOK_DIRS move-order sequence.\"\"\"
    directions = BISHOP_DIRS + ROOK_DIRS
    rays = np.full((64, 8, 7), -1, dtype=np.int8)
    counts = np.zeros((64, 8), dtype=np.int8)
    for square in range(64):
        file = square & 7
        rank = square >> 3
        for direction, (delta_file, delta_rank) in enumerate(directions):
            target_file = file + delta_file
            target_rank = rank + delta_rank
            count = 0
            while 0 <= target_file < 8 and 0 <= target_rank < 8:
                rays[square, direction, count] = target_rank * 8 + target_file
                count += 1
                target_file += delta_file
                target_rank += delta_rank
            counts[square, direction] = count
    return rays, counts


SLIDER_RAYS, SLIDER_RAY_COUNTS = _build_slider_rays()
"""

ATTACK_REPLACEMENT = '''@njit(cache=False)
def is_square_attacked(board: np.ndarray, target: int, by_side: int) -> bool:
    target_file = target & 7
    target_rank = target >> 3

    source_rank = target_rank - by_side
    if 0 <= source_rank < 8:
        for delta_file in (-1, 1):
            source_file = target_file - delta_file
            if 0 <= source_file < 8:
                source = _square(source_file, source_rank)
                if board[source] == by_side * PAWN:
                    return True

    for index in range(int(KNIGHT_TARGET_COUNTS[target])):
        source = int(KNIGHT_TARGETS[target, index])
        if board[source] == by_side * KNIGHT:
            return True

    for index in range(int(KING_TARGET_COUNTS[target])):
        source = int(KING_TARGETS[target, index])
        if board[source] == by_side * KING:
            return True

    for direction in range(4):
        for index in range(int(SLIDER_RAY_COUNTS[target, direction])):
            source = int(SLIDER_RAYS[target, direction, index])
            piece = int(board[source])
            if piece != EMPTY:
                if piece == by_side * BISHOP or piece == by_side * QUEEN:
                    return True
                break

    for direction in range(4, 8):
        for index in range(int(SLIDER_RAY_COUNTS[target, direction])):
            source = int(SLIDER_RAYS[target, direction, index])
            piece = int(board[source])
            if piece != EMPTY:
                if piece == by_side * ROOK or piece == by_side * QUEEN:
                    return True
                break

    return False
'''

FULL_SLIDER_OLD = '''        directions = BISHOP_DIRS if piece == BISHOP else ROOK_DIRS
        if piece == QUEEN:
            for delta_file, delta_rank in BISHOP_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while _inside(target_file, target_rank):
                    target = _square(target_file, target_rank)
                    target_piece = int(board[target])
                    if target_piece == EMPTY:
                        count = _append(moves, count, encode_move(from_square, target))
                    else:
                        if target_piece * side < 0 and abs(target_piece) != KING:
                            count = _append(moves, count, encode_move(from_square, target))
                        break
                    target_file += delta_file
                    target_rank += delta_rank
            directions = ROOK_DIRS

        for delta_file, delta_rank in directions:
            target_file = file + delta_file
            target_rank = rank + delta_rank
            while _inside(target_file, target_rank):
                target = _square(target_file, target_rank)
                target_piece = int(board[target])
                if target_piece == EMPTY:
                    count = _append(moves, count, encode_move(from_square, target))
                else:
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append(moves, count, encode_move(from_square, target))
                    break
                target_file += delta_file
                target_rank += delta_rank
'''

FULL_SLIDER_NEW = '''        direction_start = 0 if piece != ROOK else 4
        direction_end = 4 if piece == BISHOP else 8
        for direction in range(direction_start, direction_end):
            for ray_index in range(int(SLIDER_RAY_COUNTS[from_square, direction])):
                target = int(SLIDER_RAYS[from_square, direction, ray_index])
                target_piece = int(board[target])
                if target_piece == EMPTY:
                    count = _append(moves, count, encode_move(from_square, target))
                else:
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append(moves, count, encode_move(from_square, target))
                    break
'''

TACTICAL_SLIDER_OLD = '''        directions = BISHOP_DIRS if piece == BISHOP else ROOK_DIRS
        if piece == QUEEN:
            for delta_file, delta_rank in BISHOP_DIRS:
                target_file = file + delta_file
                target_rank = rank + delta_rank
                while _inside(target_file, target_rank):
                    target = _square(target_file, target_rank)
                    target_piece = int(board[target])
                    if target_piece != EMPTY:
                        if target_piece * side < 0 and abs(target_piece) != KING:
                            count = _append(moves, count, encode_move(from_square, target))
                        break
                    target_file += delta_file
                    target_rank += delta_rank
            directions = ROOK_DIRS

        for delta_file, delta_rank in directions:
            target_file = file + delta_file
            target_rank = rank + delta_rank
            while _inside(target_file, target_rank):
                target = _square(target_file, target_rank)
                target_piece = int(board[target])
                if target_piece != EMPTY:
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append(moves, count, encode_move(from_square, target))
                    break
                target_file += delta_file
                target_rank += delta_rank
'''

TACTICAL_SLIDER_NEW = '''        direction_start = 0 if piece != ROOK else 4
        direction_end = 4 if piece == BISHOP else 8
        for direction in range(direction_start, direction_end):
            for ray_index in range(int(SLIDER_RAY_COUNTS[from_square, direction])):
                target = int(SLIDER_RAYS[from_square, direction, ray_index])
                target_piece = int(board[target])
                if target_piece != EMPTY:
                    if target_piece * side < 0 and abs(target_piece) != KING:
                        count = _append(moves, count, encode_move(from_square, target))
                    break
'''

LEGALITY_OLD = '''    # Slider checkers and absolute pins. Scan each king ray once.
    for family in range(2):
        directions = BISHOP_DIRS if family == 0 else ROOK_DIRS
        for delta_file, delta_rank in directions:
            file = king_file + delta_file
            rank = king_rank + delta_rank
            blocker = -1
            while _inside(file, rank):
                square = _square(file, rank)
                signed_piece = int(board[square])
                if signed_piece == EMPTY:
                    file += delta_file
                    rank += delta_rank
                    continue
                if signed_piece * side > 0:
                    if blocker < 0:
                        blocker = square
                        file += delta_file
                        rank += delta_rank
                        continue
                    break

                kind = abs(signed_piece)
                slider = (
                    kind == QUEEN
                    or (family == 0 and kind == BISHOP)
                    or (family == 1 and kind == ROOK)
                )
                if slider:
                    if blocker < 0:
                        check_count += 1
                        checker_square = square
                        checker_is_slider = 1
                    else:
                        pinned |= np.uint64(1) << np.uint64(blocker)
                break
'''

LEGALITY_NEW = '''    # Slider checkers and absolute pins. Scan each precomputed king ray once.
    for direction in range(8):
        blocker = -1
        for ray_index in range(int(SLIDER_RAY_COUNTS[own_king, direction])):
            square = int(SLIDER_RAYS[own_king, direction, ray_index])
            signed_piece = int(board[square])
            if signed_piece == EMPTY:
                continue
            if signed_piece * side > 0:
                if blocker < 0:
                    blocker = square
                    continue
                break

            kind = abs(signed_piece)
            slider = (
                kind == QUEEN
                or (direction < 4 and kind == BISHOP)
                or (direction >= 4 and kind == ROOK)
            )
            if slider:
                if blocker < 0:
                    check_count += 1
                    checker_square = square
                    checker_is_slider = 1
                else:
                    pinned |= np.uint64(1) << np.uint64(blocker)
            break
'''


def replace_exact(source: str, old: str, new: str, label: str, expected: int = 1) -> str:
    count = source.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected}, found {count}")
    return source.replace(old, new, expected)


def patch(path: Path) -> None:
    source = path.read_text()
    if "SLIDER_RAYS" in source:
        raise SystemExit("source already contains slider-ray optimization")

    source = replace_exact(source, TARGETS_ANCHOR, TARGETS_REPLACEMENT, "ray tables")

    attack_start = source.index('@njit(cache=False)\ndef is_square_attacked(')
    attack_end = source.index('\n\n@njit(cache=False)\ndef in_check(', attack_start)
    source = source[:attack_start] + ATTACK_REPLACEMENT + source[attack_end:]

    source = replace_exact(source, FULL_SLIDER_OLD, FULL_SLIDER_NEW, "full slider generator")
    source = replace_exact(
        source, TACTICAL_SLIDER_OLD, TACTICAL_SLIDER_NEW, "tactical slider generator"
    )
    source = replace_exact(source, LEGALITY_OLD, LEGALITY_NEW, "legality ray scan")

    if source.count("SLIDER_RAY_COUNTS") < 8:
        raise SystemExit("unexpectedly few slider-ray uses after patch")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
