#!/usr/bin/env python3
"""Integrate a generated Rust-teacher opening/reply book into packaged Python V15.

Book hits preserve the production agent's game-history and clock-feedback state, validate legality,
and bypass search. Book misses are exactly the normal engine path.
"""
from pathlib import Path
import shutil
import sys

if len(sys.argv) != 4:
    raise SystemExit("usage: patch_v15_python_rust_book.py AGENT.py BOOK.json SUBMISSION_BOOK.json")
agent_path = Path(sys.argv[1])
book_src = Path(sys.argv[2])
book_dst = Path(sys.argv[3])
if not book_src.is_file():
    raise SystemExit(f"missing book: {book_src}")

s = agent_path.read_text()
old = "import time\n"
new = "import json\nimport time\n"
if s.count(old) != 1:
    raise SystemExit(f"import anchor count={s.count(old)}")
s = s.replace(old, new, 1)

old = '''_KPK_TABLE = np.fromfile(Path(__file__).with_name("v14_kpk.u8"), dtype=np.uint8)
if _KPK_TABLE.size != 196_608:
    raise ValueError("invalid V14 KPK bitbase")
'''
new = old + '''
_RUST_BOOK_PAYLOAD = json.loads(Path(__file__).with_name("v15_rust_book.json").read_text())
if _RUST_BOOK_PAYLOAD.get("format") != "little-gambit-rust-teacher-book-v1":
    raise ValueError("invalid V15 Rust-teacher book")
_RUST_BOOK = _RUST_BOOK_PAYLOAD["entries"]
'''
if s.count(old) != 1:
    raise SystemExit(f"book-load anchor count={s.count(old)}")
s = s.replace(old, new, 1)

anchor = '''def _position_key(board: chess.Board) -> int:
    encoded = encode_position(board)
    key = position_key(encoded.board, encoded.side, encoded.castling, encoded.ep_square)
    return int(key) & 0xFFFFFFFFFFFFFFFF


'''
insert = anchor + '''def _rust_book_move(board: chess.Board) -> chess.Move | None:
    # Builder and runtime both use python-chess canonical FEN, including only legal en-passant.
    key = " ".join(board.fen().split()[:4])
    entry = _RUST_BOOK.get(key)
    if entry is None:
        return None
    move = chess.Move.from_uci(str(entry["move"]))
    if move not in board.legal_moves:
        # A stale/corrupt book must never produce an illegal tournament move.
        return None
    return move


'''
if s.count(anchor) != 1:
    raise SystemExit(f"book-helper anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)

old = '''    history_keys = _sync_game_history(board, continued)
    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    result = search_position(board, time_left_ms, history_keys)
'''
new = '''    history_keys = _sync_game_history(board, continued)

    book_move = _rust_book_move(board)
    if book_move is not None:
        _record_our_move(board, book_move)
        _LAST_CALL_TIME_LEFT_MS = int(time_left_ms)
        _LAST_GET_MOVE_ELAPSED_MS = max(0.0, (time.perf_counter() - call_start) * 1000.0)
        return book_move.uci()

    _TT_TABLE[TT_GENERATION_INDEX] = np.uint64(
        (int(_TT_TABLE[TT_GENERATION_INDEX]) + 1) & 31
    )
    result = search_position(board, time_left_ms, history_keys)
'''
if s.count(old) != 1:
    raise SystemExit(f"get_move anchor count={s.count(old)}")
s = s.replace(old, new, 1)

agent_path.write_text(s)
book_dst.parent.mkdir(parents=True, exist_ok=True)
shutil.copyfile(book_src, book_dst)
