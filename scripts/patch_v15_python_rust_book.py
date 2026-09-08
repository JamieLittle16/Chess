#!/usr/bin/env python3
"""Add the own-Rust V15 ladder opening book to an exact packaged Python agent.

The book is advisory only in the sense that an absent/invalid entry falls straight through to the
existing search. A hit is still validated against python-chess legal moves and updates the exact same
game-history and clock-feedback state as a searched move.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_rust_book.py AGENT.py")
p = Path(sys.argv[1])
s = p.read_text()

old = "import time\n"
new = "import json\nimport time\n"
if s.count(old) != 1:
    raise SystemExit(f"import anchor count={s.count(old)}")
s = s.replace(old, new, 1)

anchor = '''_KPK_TABLE = np.fromfile(Path(__file__).with_name("v14_kpk.u8"), dtype=np.uint8)
if _KPK_TABLE.size != 196_608:
    raise ValueError("invalid V14 KPK bitbase")
'''
insert = anchor + '''
_BOOK_PAYLOAD = json.loads(Path(__file__).with_name("v15_rust_ladder_book.json").read_text())
_RUST_LADDER_BOOK: dict[str, str] = dict(_BOOK_PAYLOAD.get("entries", {}))
if not _RUST_LADDER_BOOK:
    raise ValueError("empty V15 Rust ladder book")


def _book_key(board: chess.Board) -> str:
    return " ".join(board.fen(en_passant="fen").split()[:4])


def _rust_book_move(board: chess.Board) -> chess.Move | None:
    uci = _RUST_LADDER_BOOK.get(_book_key(board))
    if uci is None:
        return None
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if move in board.legal_moves else None
'''
if s.count(anchor) != 1:
    raise SystemExit(f"KPK anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

old = '''    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    result = search_position(board, time_left_ms, history_keys)
'''
new = '''    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    booked = _rust_book_move(board)
    if booked is not None:
        _record_our_move(board, booked)
        _LAST_CALL_TIME_LEFT_MS = int(time_left_ms)
        _LAST_GET_MOVE_ELAPSED_MS = max(0.0, (time.perf_counter() - call_start) * 1000.0)
        return booked.uci()

    result = search_position(board, time_left_ms, history_keys)
'''
if s.count(old) != 1:
    raise SystemExit(f"get_move anchor count={s.count(old)}")
s = s.replace(old, new, 1)

p.write_text(s)
