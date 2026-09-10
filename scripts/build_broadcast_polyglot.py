from __future__ import annotations

import argparse
import io
import struct
from collections import defaultdict
from pathlib import Path

import chess
import chess.pgn
import chess.polyglot
import zstandard as zstd

ENTRY = struct.Struct(">QHHI")


def raw_polyglot_move(board: chess.Board, move: chess.Move) -> int:
    to_sq = move.to_square
    if board.is_castling(move):
        # Polyglot stores castling as king -> rook square.
        if move.from_square == chess.E1:
            to_sq = chess.H1 if move.to_square == chess.G1 else chess.A1
        elif move.from_square == chess.E8:
            to_sq = chess.H8 if move.to_square == chess.G8 else chess.A8
    promotion = 0 if move.promotion is None else int(move.promotion) - 1
    return int(to_sq) | (int(move.from_square) << 6) | (promotion << 12)


def parse_elo(headers: chess.pgn.Headers, key: str) -> int | None:
    try:
        value = int(headers.get(key, ""))
        return value if value > 0 else None
    except (TypeError, ValueError):
        return None


def consume_file(
    path: Path,
    max_ply: int,
    all_counts: dict[tuple[int, int], int],
    hi_counts: dict[tuple[int, int], int],
    hi_min_elo: int,
) -> tuple[int, int]:
    games = 0
    hi_games = 0
    dctx = zstd.ZstdDecompressor()
    with path.open("rb") as raw, dctx.stream_reader(raw) as zr:
        text = io.TextIOWrapper(zr, encoding="utf-8", errors="replace")
        while True:
            try:
                game = chess.pgn.read_game(text)
            except Exception as exc:  # malformed broadcast should not kill the corpus build
                print(f"PGN parse warning: {exc}", flush=True)
                continue
            if game is None:
                break
            games += 1
            we = parse_elo(game.headers, "WhiteElo")
            be = parse_elo(game.headers, "BlackElo")
            high = we is not None and be is not None and min(we, be) >= hi_min_elo
            hi_games += int(high)
            board = game.board()
            for move in game.mainline_moves():
                if board.ply() > max_ply:
                    break
                if board.chess960 or not board.is_legal(move):
                    break
                key = int(chess.polyglot.zobrist_hash(board))
                raw_move = raw_polyglot_move(board, move)
                k = (key, raw_move)
                all_counts[k] = all_counts.get(k, 0) + 1
                if high:
                    hi_counts[k] = hi_counts.get(k, 0) + 1
                board.push(move)
            if games % 10_000 == 0:
                print(
                    f"{path.name}: games={games} high={hi_games} "
                    f"all_entries={len(all_counts)} hi_entries={len(hi_counts)}",
                    flush=True,
                )
    return games, hi_games


def write_book(counts: dict[tuple[int, int], int], path: Path, min_count: int) -> tuple[int, int]:
    rows = [(k, m, c) for (k, m), c in counts.items() if c >= min_count]
    rows.sort(key=lambda x: (x[0], x[1]))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as f:
        for key, move, count in rows:
            f.write(ENTRY.pack(key, move, min(65535, count), 0))
    return len(rows), path.stat().st_size


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, nargs="+", required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-ply", type=int, default=22)
    p.add_argument("--hi-min-elo", type=int, default=2350)
    args = p.parse_args()

    all_counts: dict[tuple[int, int], int] = {}
    hi_counts: dict[tuple[int, int], int] = {}
    total_games = total_hi = 0
    for path in args.input:
        g, h = consume_file(path, args.max_ply, all_counts, hi_counts, args.hi_min_elo)
        total_games += g
        total_hi += h

    out = args.output_dir
    variants = [
        ("broadcast-all-min1.bin", all_counts, 1),
        ("broadcast-all-min2.bin", all_counts, 2),
        ("broadcast-all-min3.bin", all_counts, 3),
        ("broadcast-hi-min1.bin", hi_counts, 1),
        ("broadcast-hi-min2.bin", hi_counts, 2),
    ]
    for name, counts, minimum in variants:
        entries, size = write_book(counts, out / name, minimum)
        print(f"BOOK {name} entries={entries} bytes={size} min_count={minimum}")
    print(
        f"DONE games={total_games} high_elo_games={total_hi} max_ply={args.max_ply} "
        f"hi_min_elo={args.hi_min_elo} unique_all={len(all_counts)} unique_hi={len(hi_counts)}"
    )


if __name__ == "__main__":
    main()
