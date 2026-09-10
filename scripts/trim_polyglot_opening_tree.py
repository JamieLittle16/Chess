from __future__ import annotations

import argparse
import struct
from collections import deque
from pathlib import Path

import chess
import chess.polyglot

ENTRY = struct.Struct(">QHHI")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--max-ply", type=int, default=22)
    args = p.parse_args()

    q: deque[chess.Board] = deque([chess.Board()])
    seen: set[int] = set()
    kept: list[tuple[int, int, int, int]] = []
    positions = 0
    max_queue = 1

    with chess.polyglot.open_reader(args.input) as reader:
        while q:
            b = q.popleft()
            key = int(chess.polyglot.zobrist_hash(b))
            if key in seen:
                continue
            seen.add(key)
            if b.ply() > args.max_ply:
                continue

            legal = set(b.legal_moves)
            entries = [e for e in reader.find_all(b) if e.move in legal and int(e.weight) > 0]
            if not entries:
                continue
            positions += 1
            for e in entries:
                kept.append((int(e.key), int(e.raw_move), int(e.weight), int(e.learn)))
                if b.ply() < args.max_ply:
                    child = b.copy(stack=False)
                    child.push(e.move)
                    q.append(child)
            if len(q) > max_queue:
                max_queue = len(q)
            if positions % 100_000 == 0:
                print(f"positions={positions} entries={len(kept)} seen={len(seen)} queue={len(q)}", flush=True)

    # Polyglot readers expect entries sorted by full 64-bit key.
    kept.sort(key=lambda x: (x[0], x[1], -x[2], x[3]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as f:
        for key, raw_move, weight, learn in kept:
            f.write(ENTRY.pack(key, raw_move, weight, learn))

    print(
        f"DONE max_ply={args.max_ply} positions={positions} entries={len(kept)} "
        f"bytes={args.output.stat().st_size} seen={len(seen)} max_queue={max_queue}",
        flush=True,
    )


if __name__ == "__main__":
    main()
