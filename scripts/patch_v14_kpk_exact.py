#!/usr/bin/env python3
"""Patch V13 agent.py with a root-only exact KPK win/draw+conversion-distance override."""
from __future__ import annotations

import argparse
from pathlib import Path


def replace_once(source: str, old: str, new: str, label: str) -> str:
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch(path: Path) -> None:
    source = path.read_text()
    if "_KPK_TABLE" in source:
        raise SystemExit("KPK patch already applied")
    source = replace_once(
        source,
        "from dataclasses import dataclass\nfrom typing import Final\n",
        "from dataclasses import dataclass\nfrom pathlib import Path\nfrom typing import Final\n",
        "Path import",
    )
    source = replace_once(
        source,
        "import numpy as np\n\nfrom experiments.numba_core",
        """import numpy as np

_KPK_TABLE = np.fromfile(Path(__file__).with_name("v14_kpk.u8"), dtype=np.uint8)
if _KPK_TABLE.size != 196_608:
    raise ValueError("invalid V14 KPK bitbase")

from experiments.numba_core""",
        "table load",
    )

    anchor = '''def get_move(fen: str, time_left_ms: int) -> str:
'''
    helper = '''def _kpk_probe(board: chess.Board) -> tuple[bool, int] | None:
    """Return (pawn_side_forces_win, conversion_distance_plies) for exact KPK roots."""
    if len(board.piece_map()) != 3:
        return None
    pawns = list(board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK))
    if len(pawns) != 1:
        return None
    pawn = pawns[0]
    pawn_side = board.color_at(pawn)
    if pawn_side is None:
        return None
    strong = board.king(pawn_side)
    weak = board.king(not pawn_side)
    if strong is None or weak is None:
        return None

    # Normalize a black pawn by vertical reflection so the pawn always advances toward rank 8.
    if pawn_side == chess.BLACK:
        strong ^= 56
        weak ^= 56
        pawn ^= 56
    strong_to_move = board.turn == pawn_side

    # Mirror files e-h into a-d, matching the compact 24-pawn-square table.
    if chess.square_file(pawn) >= 4:
        strong ^= 7
        weak ^= 7
        pawn ^= 7
    file = chess.square_file(pawn)
    rank = chess.square_rank(pawn)
    if not (0 <= file < 4 and 1 <= rank <= 6):
        return None
    pidx = (rank - 1) * 4 + file
    stm = 0 if strong_to_move else 1
    index = stm * (24 * 4096) + pidx * 4096 + strong * 64 + weak
    encoded = int(_KPK_TABLE[index])
    return encoded != 0, max(0, encoded - 1)


def _kpk_child_value(parent: chess.Board, move: chess.Move) -> tuple[bool, int] | None:
    pawn_square = next(iter(parent.pieces(chess.PAWN, chess.WHITE) | parent.pieces(chess.PAWN, chess.BLACK)))
    pawn_side = parent.color_at(pawn_square)
    child = parent.copy(stack=False)
    child.push(move)
    probe = _kpk_probe(child)
    if probe is not None:
        win, distance = probe
        return win, distance + 1

    # The only exits from KPK are pawn capture or promotion.
    if not child.pieces(chess.PAWN, chess.WHITE) and not child.pieces(chess.PAWN, chess.BLACK):
        if move.promotion is None:
            return False, 1
        if child.is_stalemate():
            return False, 1
        if child.is_checkmate() or move.promotion in (chess.QUEEN, chess.ROOK):
            return True, 1
        return False, 1
    return None


def _kpk_exact_override(
    board: chess.Board,
    searched: chess.Move,
    legal_moves: list[chess.Move],
) -> chess.Move:
    """Keep V13 unless its KPK result/distance is provably inferior."""
    root = _kpk_probe(board)
    if root is None or board.halfmove_clock > 20:
        return searched
    pawn_square = next(iter(board.pieces(chess.PAWN, chess.WHITE) | board.pieces(chess.PAWN, chess.BLACK)))
    pawn_side = board.color_at(pawn_square)
    infos: list[tuple[chess.Move, bool, int]] = []
    for move in legal_moves:
        value = _kpk_child_value(board, move)
        if value is not None:
            infos.append((move, value[0], value[1]))
    if not infos:
        return searched
    current = next((row for row in infos if row[0] == searched), None)

    if board.turn == pawn_side:
        winning = [row for row in infos if row[1]]
        if not winning:
            return searched
        best_distance = min(row[2] for row in winning)
        if current is not None and current[1] and current[2] <= best_distance:
            return searched
        return next(row[0] for row in winning if row[2] == best_distance)

    drawing = [row for row in infos if not row[1]]
    if drawing:
        if current is not None and not current[1]:
            return searched
        return drawing[0][0]
    # Lost KPK: maximize exact conversion distance rather than walking into a shorter loss.
    best_distance = max(row[2] for row in infos)
    if current is not None and current[2] >= best_distance:
        return searched
    return next(row[0] for row in infos if row[2] == best_distance)


def get_move(fen: str, time_left_ms: int) -> str:
'''
    source = replace_once(source, anchor, helper, "KPK helper insertion")

    old = '''    result = search_position(board, time_left_ms, history_keys)
    _record_our_move(board, result.move)

    _LAST_CALL_TIME_LEFT_MS = int(time_left_ms)
    _LAST_GET_MOVE_ELAPSED_MS = max(0.0, (time.perf_counter() - call_start) * 1000.0)
    return result.move.uci()
'''
    new = '''    result = search_position(board, time_left_ms, history_keys)
    selected = _kpk_exact_override(board, result.move, list(board.legal_moves))
    _record_our_move(board, selected)

    _LAST_CALL_TIME_LEFT_MS = int(time_left_ms)
    _LAST_GET_MOVE_ELAPSED_MS = max(0.0, (time.perf_counter() - call_start) * 1000.0)
    return selected.uci()
'''
    source = replace_once(source, old, new, "get_move override")
    path.write_text(source)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    patch(args.path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
