#!/usr/bin/env python3
"""Patch exact V13 with cheap main-search-only defended-capture ordering variants.

The expensive SEE-A experiment showed a useful equal-node signal but cost ~20% NPS.  These variants
preserve the idea (demote adverse-MVV captures that look defended) while removing recursive exchange
simulation, board mutation and all qsearch overhead.  They change ordering only: no move is removed,
pruned, reclassified as quiet/tactical, or given a different evaluation.

Variants:
  b1  all adverse-MVV captures; one current-position attack probe; exempt direct checks
  b2  as b1, but require attacker-victim value gap >= 200cp
  b3  as b2, without the direct-check exemption (cheapest full-defender probe)
  b4  gap >= 200cp and only a pawn-defender probe (very cheap poisoned-pawn classifier)
"""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def variant_body(variant: str) -> str:
    if variant == "b1":
        gate = """    if target_value >= attacker_value:\n        return False\n"""
        check = """    if _direct_check_after_move(board, move, opponent_king):\n        return False\n    return is_square_attacked(board, to_square, -side)\n"""
    elif variant == "b2":
        gate = """    if target_value >= attacker_value or attacker_value - target_value < 200:\n        return False\n"""
        check = """    if _direct_check_after_move(board, move, opponent_king):\n        return False\n    return is_square_attacked(board, to_square, -side)\n"""
    elif variant == "b3":
        gate = """    if target_value >= attacker_value or attacker_value - target_value < 200:\n        return False\n"""
        check = """    return is_square_attacked(board, to_square, -side)\n"""
    elif variant == "b4":
        gate = """    if target_value >= attacker_value or attacker_value - target_value < 200:\n        return False\n"""
        check = """    defender = -side\n    target_file = to_square & 7\n    target_rank = to_square >> 3\n    source_rank = target_rank - defender\n    if source_rank < 0 or source_rank >= 8:\n        return False\n    left = target_file - 1\n    if left >= 0 and int(board[source_rank * 8 + left]) == defender * PAWN:\n        return True\n    right = target_file + 1\n    return right < 8 and int(board[source_rank * 8 + right]) == defender * PAWN\n"""
    else:
        raise SystemExit(f"unsupported variant {variant!r}")
    return gate + check


def patch(path: Path, variant: str) -> None:
    if variant not in {"b1", "b2", "b3", "b4"}:
        raise SystemExit("variant must be one of b1,b2,b3,b4")
    source = path.read_text()

    anchor = '''@njit(cache=False)\ndef _order_moves(\n'''
    helper = '''@njit(cache=False, inline="always")
def _direct_check_after_move(board: np.ndarray, move: int, opponent_king: int) -> bool:
    """Cheap direct-check test with the from-square treated as vacated; discovered checks are ignored."""
    if opponent_king < 0:
        return False
    from_square = move_from(move)
    to_square = move_to(move)
    signed_piece = int(board[from_square])
    side = WHITE if signed_piece > 0 else -WHITE
    piece = abs(signed_piece)
    to_file = to_square & 7
    to_rank = to_square >> 3
    king_file = opponent_king & 7
    king_rank = opponent_king >> 3
    df = king_file - to_file
    dr = king_rank - to_rank

    if piece == PAWN:
        return dr == side and (df == -1 or df == 1)
    if piece == KNIGHT:
        adf = abs(df)
        adr = abs(dr)
        return (adf == 1 and adr == 2) or (adf == 2 and adr == 1)
    if piece == KING:
        return abs(df) <= 1 and abs(dr) <= 1

    step_file = 0
    step_rank = 0
    if piece == BISHOP:
        if abs(df) != abs(dr) or df == 0:
            return False
        step_file = 1 if df > 0 else -1
        step_rank = 1 if dr > 0 else -1
    elif piece == ROOK:
        if df != 0 and dr != 0:
            return False
        if df != 0:
            step_file = 1 if df > 0 else -1
        else:
            step_rank = 1 if dr > 0 else -1
    elif piece == QUEEN:
        if abs(df) == abs(dr) and df != 0:
            step_file = 1 if df > 0 else -1
            step_rank = 1 if dr > 0 else -1
        elif df == 0 and dr != 0:
            step_rank = 1 if dr > 0 else -1
        elif dr == 0 and df != 0:
            step_file = 1 if df > 0 else -1
        else:
            return False
    else:
        return False

    file = to_file + step_file
    rank = to_rank + step_rank
    while file != king_file or rank != king_rank:
        square = rank * 8 + file
        if square != from_square and int(board[square]) != EMPTY:
            return False
        file += step_file
        rank += step_rank
    return True


@njit(cache=False, inline="always")
def _bad_defended_capture_main(board: np.ndarray, move: int, opponent_king: int) -> bool:
    if move_promotion(move) != 0 or (move & FLAG_EP):
        return False
    from_square = move_from(move)
    to_square = move_to(move)
    target = abs(int(board[to_square]))
    if target == 0:
        return False
    attacker = abs(int(board[from_square]))
    attacker_value = int(PIECE_VALUE[attacker])
    target_value = int(PIECE_VALUE[target])
    side = WHITE if int(board[from_square]) > 0 else -WHITE
VARIANT_BODY


@njit(cache=False, inline="always")
def _move_order_score_main(board: np.ndarray, move: int, preferred: int, opponent_king: int) -> int:
    score = _move_order_score(board, move, preferred)
    if move != preferred and _bad_defended_capture_main(board, move, opponent_king):
        score -= 2_200_000
    return score


@njit(cache=False)
def _order_root_moves(
    board: np.ndarray,
    moves: np.ndarray,
    count: int,
    preferred: int,
    scores: np.ndarray,
    opponent_king: int,
) -> None:
    for index in range(count):
        scores[index] = _move_order_score_main(board, int(moves[index]), preferred, opponent_king)
    for index in range(1, count):
        move = int(moves[index])
        score = int(scores[index])
        cursor = index - 1
        while cursor >= 0 and int(scores[cursor]) < score:
            moves[cursor + 1] = moves[cursor]
            scores[cursor + 1] = scores[cursor]
            cursor -= 1
        moves[cursor + 1] = move
        scores[cursor + 1] = score


@njit(cache=False)
def _order_moves(
'''.replace('VARIANT_BODY', variant_body(variant).rstrip())
    source = replace_once(source, anchor, helper, "main-order helper insertion")

    old_sig = '''def _order_moves_with_killers(\n    board: np.ndarray,\n    moves: np.ndarray,\n    count: int,\n    preferred: int,\n    scores: np.ndarray,\n    killer0: int,\n    killer1: int,\n) -> None:\n'''
    new_sig = '''def _order_moves_with_killers(\n    board: np.ndarray,\n    moves: np.ndarray,\n    count: int,\n    preferred: int,\n    scores: np.ndarray,\n    killer0: int,\n    killer1: int,\n    opponent_king: int,\n) -> None:\n'''
    source = replace_once(source, old_sig, new_sig, "killer-order signature")
    source = replace_once(
        source,
        "        score = _move_order_score(board, move, preferred)\n        if score < 5_040_000:\n",
        "        score = _move_order_score_main(board, move, preferred, opponent_king)\n        if score < 5_040_000:\n",
        "killer-order scoring",
    )

    old_call = '''    _order_moves_with_killers(\n        board,\n        moves,\n        count,\n        preferred,\n        score_stack[ply],\n        int(killers[ply, 0]),\n        int(killers[ply, 1]),\n    )\n'''
    new_call = '''    opponent_king = int(\n        eval_stack[ply][EVAL_BLACK_KING] if side == WHITE else eval_stack[ply][EVAL_WHITE_KING]\n    )\n    _order_moves_with_killers(\n        board,\n        moves,\n        count,\n        preferred,\n        score_stack[ply],\n        int(killers[ply, 0]),\n        int(killers[ply, 1]),\n        opponent_king,\n    )\n'''
    source = replace_once(source, old_call, new_call, "recursive main-order call")

    old_root = "    _order_moves(board, moves, count, preferred, score_stack[0])\n"
    new_root = '''    opponent_king = int(\n        eval_stack[0][EVAL_BLACK_KING] if side == WHITE else eval_stack[0][EVAL_WHITE_KING]\n    )\n    _order_root_moves(board, moves, count, preferred, score_stack[0], opponent_king)\n'''
    source = replace_once(source, old_root, new_root, "root main-order call")

    markers = ["_bad_defended_capture_main", "_move_order_score_main", "_order_root_moves", "score -= 2_200_000"]
    for marker in markers:
        if marker not in source:
            raise SystemExit(f"missing marker after patch: {marker}")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--variant", choices=("b1", "b2", "b3", "b4"), required=True)
    args = parser.parse_args()
    patch(args.path, args.variant)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
