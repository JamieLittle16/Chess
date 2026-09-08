#!/usr/bin/env python3
"""Build a tiny exact K+P-vs-K win/draw + distance table for Little Gambit V14.

The state space is normalized to a white pawn on files a-d, ranks 2-7.  Outcomes are derived by a
plain game-graph fixed point: the pawn side chooses a winning successor; the bare king chooses a
drawing successor when one exists. Unresolved cycles are draws. A second pass derives distance to
promotion/checkmate inside winning states so V14 can prefer clean technical conversion.

Output is 196,608 uint8 cells. 0 means draw/invalid; positive N means a forced win with distance
N-1 plies in this normalized no-50-move KPK game. Runtime code uses it only when the actual root has
exactly K+P vs K and a low halfmove clock.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

FILES = 4
PAWN_STATES = 24
PLANE = 64 * 64
STRONG_TO_MOVE = 0
WEAK_TO_MOVE = 1
UNKNOWN = 0
DRAW = 1
WIN = 2
INVALID = 3


def inside(square: int) -> bool:
    return 0 <= square < 64


def file_of(square: int) -> int:
    return square & 7


def rank_of(square: int) -> int:
    return square >> 3


def king_adjacent(a: int, b: int) -> bool:
    return max(abs(file_of(a) - file_of(b)), abs(rank_of(a) - rank_of(b))) <= 1


def pawn_attacks(pawn: int, square: int) -> bool:
    if rank_of(pawn) >= 7:
        return False
    return rank_of(square) == rank_of(pawn) + 1 and abs(file_of(square) - file_of(pawn)) == 1


def pawn_index(pawn: int) -> int:
    file = file_of(pawn)
    rank = rank_of(pawn)
    if not (0 <= file < 4 and 1 <= rank <= 6):
        return -1
    return (rank - 1) * 4 + file


def decode(index: int) -> tuple[int, int, int, int]:
    stm = index // (PAWN_STATES * PLANE)
    rem = index % (PAWN_STATES * PLANE)
    pidx = rem // PLANE
    rem %= PLANE
    strong = rem // 64
    weak = rem & 63
    pawn = ((pidx // 4) + 1) * 8 + (pidx & 3)
    return strong, weak, pawn, stm


def encode(strong: int, weak: int, pawn: int, stm: int) -> int:
    pidx = pawn_index(pawn)
    if pidx < 0:
        return -1
    return stm * PAWN_STATES * PLANE + pidx * PLANE + strong * 64 + weak


def legal_state(strong: int, weak: int, pawn: int, stm: int) -> bool:
    if strong == weak or strong == pawn or weak == pawn:
        return False
    if king_adjacent(strong, weak):
        return False
    if pawn_index(pawn) < 0:
        return False
    # If it is the pawn side's turn, the bare king made the previous move and cannot have left
    # itself in pawn check. A checked bare king is legal only when it is currently its own turn.
    if stm == STRONG_TO_MOVE and pawn_attacks(pawn, weak):
        return False
    return True


def king_targets(square: int):
    f0 = file_of(square)
    r0 = rank_of(square)
    for dr in (-1, 0, 1):
        for df in (-1, 0, 1):
            if df == 0 and dr == 0:
                continue
            f = f0 + df
            r = r0 + dr
            if 0 <= f < 8 and 0 <= r < 8:
                yield r * 8 + f


def slider_attacks(piece_square: int, target: int, strong_king: int, queen: bool) -> bool:
    df = file_of(target) - file_of(piece_square)
    dr = rank_of(target) - rank_of(piece_square)
    rook_line = df == 0 or dr == 0
    bishop_line = abs(df) == abs(dr)
    if not rook_line and not (queen and bishop_line):
        return False
    if rook_line and df != 0 and dr != 0:
        return False
    step_f = 0 if df == 0 else (1 if df > 0 else -1)
    step_r = 0 if dr == 0 else (1 if dr > 0 else -1)
    f = file_of(piece_square) + step_f
    r = rank_of(piece_square) + step_r
    while (f, r) != (file_of(target), rank_of(target)):
        sq = r * 8 + f
        if sq == strong_king:
            return False
        f += step_f
        r += step_r
    return True


def promoted_position_is_win(strong: int, weak: int, promotion_square: int, queen: bool) -> bool:
    checked = slider_attacks(promotion_square, weak, strong, queen)
    any_move = False
    for target in king_targets(weak):
        if target == strong or target == promotion_square:
            continue
        if king_adjacent(target, strong):
            continue
        if slider_attacks(promotion_square, target, strong, queen):
            continue
        any_move = True
        break
    if not any_move:
        return checked  # checkmate wins, stalemate draws
    return True  # legal KQK/KRK is a theoretical win from a fresh pawn move


def successors(strong: int, weak: int, pawn: int, stm: int):
    """Yield (kind, payload), where kind is 'state', 'win', or 'draw'."""
    if stm == STRONG_TO_MOVE:
        for target in king_targets(strong):
            if target == weak or target == pawn or king_adjacent(target, weak):
                continue
            yield "state", encode(target, weak, pawn, WEAK_TO_MOVE)

        one = pawn + 8
        if rank_of(pawn) == 6:
            if one != weak and one != strong:
                # Try queen and rook promotions. A legal non-stalemating KQK/KRK child is won.
                if promoted_position_is_win(strong, weak, one, True) or promoted_position_is_win(
                    strong, weak, one, False
                ):
                    yield "win", 0
                else:
                    yield "draw", 0
        elif one != weak and one != strong:
            yield "state", encode(strong, weak, one, WEAK_TO_MOVE)
            if rank_of(pawn) == 1:
                two = pawn + 16
                if two != weak and two != strong:
                    yield "state", encode(strong, weak, two, WEAK_TO_MOVE)
    else:
        for target in king_targets(weak):
            if target == strong or king_adjacent(target, strong):
                continue
            if target == pawn:
                yield "draw", 0
                continue
            if pawn_attacks(pawn, target):
                continue
            yield "state", encode(strong, target, pawn, STRONG_TO_MOVE)


def build() -> tuple[np.ndarray, np.ndarray]:
    total = 2 * PAWN_STATES * PLANE
    outcome = np.full(total, UNKNOWN, dtype=np.uint8)
    legal = np.zeros(total, dtype=np.bool_)

    for idx in range(total):
        strong, weak, pawn, stm = decode(idx)
        if not legal_state(strong, weak, pawn, stm):
            outcome[idx] = INVALID
            continue
        legal[idx] = True

    # Solve W/D by monotone fixed point. UNKNOWN cycles remaining at convergence are draws.
    changed = True
    passes = 0
    while changed:
        changed = False
        passes += 1
        for idx in range(total):
            if not legal[idx] or outcome[idx] != UNKNOWN:
                continue
            strong, weak, pawn, stm = decode(idx)
            children = list(successors(strong, weak, pawn, stm))
            if not children:
                if stm == WEAK_TO_MOVE and pawn_attacks(pawn, weak):
                    outcome[idx] = WIN
                else:
                    outcome[idx] = DRAW
                changed = True
                continue

            child_values = []
            has_external_win = False
            has_external_draw = False
            for kind, payload in children:
                if kind == "win":
                    has_external_win = True
                elif kind == "draw":
                    has_external_draw = True
                else:
                    if payload < 0 or not legal[payload]:
                        raise AssertionError((idx, kind, payload))
                    child_values.append(int(outcome[payload]))

            if stm == STRONG_TO_MOVE:
                if has_external_win or WIN in child_values:
                    outcome[idx] = WIN
                    changed = True
                elif all(value in (DRAW, INVALID) for value in child_values) and not any(
                    value == UNKNOWN for value in child_values
                ):
                    outcome[idx] = DRAW
                    changed = True
            else:
                if has_external_draw or DRAW in child_values:
                    outcome[idx] = DRAW
                    changed = True
                elif child_values and all(value == WIN for value in child_values) and not has_external_draw:
                    outcome[idx] = WIN
                    changed = True

        if passes > 256:
            raise RuntimeError("KPK WDL fixed point did not converge")

    outcome[(legal) & (outcome == UNKNOWN)] = DRAW

    # Win distance: terminal checkmate = 0. Strong chooses the shortest winning child; weak chooses
    # the longest, so a single byte also gives us a clean technical move preference at the root.
    dist = np.full(total, -1, dtype=np.int16)
    for idx in range(total):
        if outcome[idx] != WIN:
            continue
        strong, weak, pawn, stm = decode(idx)
        children = list(successors(strong, weak, pawn, stm))
        if not children and stm == WEAK_TO_MOVE and pawn_attacks(pawn, weak):
            dist[idx] = 0
        elif stm == STRONG_TO_MOVE and any(kind == "win" for kind, _ in children):
            dist[idx] = 1

    for _ in range(256):
        changed = False
        for idx in range(total):
            if outcome[idx] != WIN:
                continue
            strong, weak, pawn, stm = decode(idx)
            children = list(successors(strong, weak, pawn, stm))
            if stm == STRONG_TO_MOVE:
                candidates = []
                if any(kind == "win" for kind, _ in children):
                    candidates.append(1)
                for kind, payload in children:
                    if kind == "state" and outcome[payload] == WIN and dist[payload] >= 0:
                        candidates.append(int(dist[payload]) + 1)
                if candidates:
                    new = min(candidates)
                    if dist[idx] < 0 or new < dist[idx]:
                        dist[idx] = new
                        changed = True
            else:
                win_children = [
                    payload for kind, payload in children if kind == "state" and outcome[payload] == WIN
                ]
                if win_children and len(win_children) == len(children) and all(
                    dist[payload] >= 0 for payload in win_children
                ):
                    new = max(int(dist[payload]) for payload in win_children) + 1
                    if dist[idx] != new:
                        dist[idx] = new
                        changed = True
        if not changed:
            break
    else:
        raise RuntimeError("KPK distance fixed point did not converge")

    missing = int(np.sum((outcome == WIN) & (dist < 0)))
    if missing:
        raise RuntimeError(f"{missing} winning KPK states have no finite conversion distance")

    encoded = np.zeros(total, dtype=np.uint8)
    win_indices = np.flatnonzero(outcome == WIN)
    max_dist = int(dist[win_indices].max(initial=0))
    if max_dist >= 255:
        raise RuntimeError(f"KPK distance does not fit uint8: {max_dist}")
    encoded[win_indices] = (dist[win_indices] + 1).astype(np.uint8)
    return encoded, outcome


def verify(table: np.ndarray, outcome: np.ndarray) -> dict[str, int]:
    total = len(table)
    legal_count = 0
    win_count = 0
    draw_count = 0
    max_distance = 0
    for idx in range(total):
        strong, weak, pawn, stm = decode(idx)
        if not legal_state(strong, weak, pawn, stm):
            if table[idx] != 0:
                raise AssertionError("invalid state encoded as win")
            continue
        legal_count += 1
        children = list(successors(strong, weak, pawn, stm))
        is_win = table[idx] != 0
        if is_win:
            win_count += 1
            max_distance = max(max_distance, int(table[idx]) - 1)
        else:
            draw_count += 1

        child_wins = []
        for kind, payload in children:
            if kind == "win":
                child_wins.append(True)
            elif kind == "draw":
                child_wins.append(False)
            else:
                child_wins.append(table[payload] != 0)
        if not children:
            expected = stm == WEAK_TO_MOVE and pawn_attacks(pawn, weak)
        elif stm == STRONG_TO_MOVE:
            expected = any(child_wins)
        else:
            expected = all(child_wins)
        if is_win != expected:
            raise AssertionError((idx, strong, weak, pawn, stm, is_win, expected, children))

    return {
        "states": total,
        "legal_states": legal_count,
        "wins": win_count,
        "draws": draw_count,
        "max_win_distance_plies": max_distance,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    table, outcome = build()
    stats = verify(table, outcome)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    table.tofile(args.output)
    print(stats)
    print("bytes", args.output.stat().st_size)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
