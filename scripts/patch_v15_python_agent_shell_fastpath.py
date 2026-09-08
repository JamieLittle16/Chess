#!/usr/bin/env python3
"""Remove redundant Python-shell work around the exact packaged V14 search.

This patch intentionally does not alter compiled search semantics or clock-allocation policy. It
reuses one encoded root and one legal-move list, makes KPK enumeration lazy, and uses occupancy
popcount instead of constructing piece maps. Saved wrapper time is returned to the game clock.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()

old = '''def _position_key(board: chess.Board) -> int:
    encoded = encode_position(board)
    key = position_key(encoded.board, encoded.side, encoded.castling, encoded.ep_square)
    return int(key) & 0xFFFFFFFFFFFFFFFF
'''
new = '''def _position_key(board: chess.Board, encoded=None) -> int:
    if encoded is None:
        encoded = encode_position(board)
    key = position_key(encoded.board, encoded.side, encoded.castling, encoded.ep_square)
    return int(key) & 0xFFFFFFFFFFFFFFFF
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''def _sync_game_history(root: chess.Board, continued: bool | None = None) -> np.ndarray:
    global _GAME_KEYS
    root_key = _position_key(root)
'''
new = '''def _sync_game_history(
    root: chess.Board,
    continued: bool | None = None,
    root_key: int | None = None,
) -> np.ndarray:
    global _GAME_KEYS
    if root_key is None:
        root_key = _position_key(root)
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

s = s.replace('    pieces = len(board.piece_map())\n', '    pieces = board.occupied.bit_count()\n', 1)

old = '''def search_position(
    board: chess.Board,
    time_left_ms: int,
    history_keys: np.ndarray | None = None,
) -> SearchResult:
    """Search without mutating the supplied python-chess board."""
    legal_moves = list(board.legal_moves)
'''
new = '''def search_position(
    board: chess.Board,
    time_left_ms: int,
    history_keys: np.ndarray | None = None,
    *,
    encoded=None,
    legal_moves: list[chess.Move] | None = None,
) -> SearchResult:
    """Search without mutating the supplied python-chess board."""
    if legal_moves is None:
        legal_moves = list(board.legal_moves)
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '    encoded = encode_position(board)\n    soft_ms, hard_ms = _search_time_budgets_ms(board, time_left_ms, legal_moves)\n'
new = '''    if encoded is None:
        encoded = encode_position(board)
    soft_ms, hard_ms = _search_time_budgets_ms(board, time_left_ms, legal_moves)
'''
# There is also encode_position in evaluate/_compile. Restrict to search block by exact adjacent text.
assert s.count(old) == 1
s = s.replace(old, new, 1)

s = s.replace('        if candidate is not None and candidate in board.legal_moves:\n', '        if candidate is not None and candidate in legal_moves:\n', 1)

# KPK piece count: no dict allocation.
s = s.replace('    if len(board.piece_map()) != 3:\n', '    if board.occupied.bit_count() != 3:\n', 1)

old = '''def _kpk_exact_override(
    board: chess.Board,
    searched: chess.Move,
    legal_moves: list[chess.Move],
) -> chess.Move:
    """Keep V13 unless its KPK result/distance is provably inferior."""
    root = _kpk_probe(board)
    if root is None or board.halfmove_clock > 20:
        return searched
'''
new = '''def _kpk_exact_override(
    board: chess.Board,
    searched: chess.Move,
    legal_moves: list[chess.Move] | None = None,
) -> chess.Move:
    """Keep V13 unless its KPK result/distance is provably inferior."""
    root = _kpk_probe(board)
    if root is None or board.halfmove_clock > 20:
        return searched
    if legal_moves is None:
        legal_moves = list(board.legal_moves)
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

old = '''    history_keys = _sync_game_history(board, continued)
    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    result = search_position(board, time_left_ms, history_keys)
    selected = _kpk_exact_override(board, result.move, list(board.legal_moves))
'''
new = '''    # Encode and enumerate the root once. Both operations were previously repeated in wrapper
    # bookkeeping after already being paid for by the search path.
    encoded = encode_position(board)
    root_key = int(
        position_key(encoded.board, encoded.side, encoded.castling, encoded.ep_square)
    ) & 0xFFFFFFFFFFFFFFFF
    legal_moves = list(board.legal_moves)
    history_keys = _sync_game_history(board, continued, root_key)
    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    result = search_position(
        board,
        time_left_ms,
        history_keys,
        encoded=encoded,
        legal_moves=legal_moves,
    )
    selected = _kpk_exact_override(board, result.move, legal_moves)
'''
assert s.count(old) == 1
s = s.replace(old, new, 1)

p.write_text(s)
