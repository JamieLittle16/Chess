#!/usr/bin/env python3
"""Build a compact competition opening/reply book from the production Rust V15 teacher.

Observed Chessathon starts include which colour our agent controlled. At our turns we ask the normal
production PVS teacher for one deeper best move. At opponent turns we use shallower full-window
MultiPV only to enumerate the strongest N plausible replies. This asymmetry spends offline compute
where it directly improves moves we will actually play.

The emitted lookup key is the first four FEN fields (board, side, castling, en-passant), deliberately
ignoring move clocks. Draw/repetition semantics remain owned by the normal runtime engine.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

import chess


@dataclass(frozen=True)
class State:
    fen: str
    our_color: bool
    origin: str


def fen4(fen: str) -> str:
    return " ".join(fen.split()[:4])


def load_roots(path: Path) -> list[State]:
    rows: list[State] = []
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # The checked-in observed-start corpus historically used escaped ``\\t``
        # separators rather than literal tab bytes.  Accept both representations so
        # the research tool remains robust if the corpus is normalised later.
        parts = line.split("\t", 2)
        if len(parts) != 3:
            parts = line.split("\\t", 2)
        if len(parts) != 3:
            raise ValueError(f"bad observed-start row: {line!r}")
        color, opening, fen = parts
        if color not in {"white", "black"}:
            raise ValueError(f"bad colour {color!r}")
        board = chess.Board(fen)
        rows.append(State(board.fen(), color == "white", opening))
    return rows


def query_teacher(binary: Path, states: list[State], depth: int, width: int) -> dict[str, list[tuple[str, int]]]:
    if not states:
        return {}
    unique: dict[str, State] = {s.fen: s for s in states}
    proc = subprocess.run(
        [str(binary), str(depth), str(width)],
        input="\n".join(unique) + "\n",
        text=True,
        capture_output=True,
        check=True,
        env=os.environ.copy(),
    )
    out: dict[str, list[tuple[str, int]]] = {}
    for line in proc.stdout.splitlines():
        fen, encoded = line.split("\t", 1)
        candidates: list[tuple[str, int]] = []
        if encoded:
            for item in encoded.split(","):
                uci, score = item.rsplit(":", 1)
                candidates.append((uci, int(score)))
        out[chess.Board(fen).fen()] = candidates
    missing = set(unique) - set(out)
    if missing:
        raise RuntimeError(f"teacher omitted {len(missing)} positions")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roots", type=Path, required=True)
    ap.add_argument("--teacher-bin", type=Path, required=True)
    ap.add_argument("--our-depth", type=int, default=6)
    ap.add_argument("--opponent-depth", type=int, default=4)
    ap.add_argument("--opponent-width", type=int, default=3)
    ap.add_argument("--plies", type=int, default=6)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    if min(args.our_depth, args.opponent_depth, args.opponent_width, args.plies) < 1:
        raise SystemExit("depths, opponent-width and plies must be positive")

    roots = load_roots(args.roots)
    frontier = roots[:]
    book: dict[str, dict[str, object]] = {}
    layer_stats: list[dict[str, int]] = []

    for ply in range(args.plies):
        dedup: dict[tuple[str, bool], State] = {(s.fen, s.our_color): s for s in frontier}
        frontier = list(dedup.values())
        our_states = [s for s in frontier if chess.Board(s.fen).turn == s.our_color]
        opponent_states = [s for s in frontier if chess.Board(s.fen).turn != s.our_color]
        teacher: dict[str, list[tuple[str, int]]] = {}
        teacher.update(query_teacher(args.teacher_bin, our_states, args.our_depth, 1))
        teacher.update(query_teacher(args.teacher_bin, opponent_states, args.opponent_depth, args.opponent_width))

        nxt: dict[tuple[str, bool], State] = {}
        for state in frontier:
            board = chess.Board(state.fen)
            candidates = teacher[state.fen]
            if not candidates:
                continue
            ours = board.turn == state.our_color
            if ours:
                move_uci, score = candidates[0]
                move = chess.Move.from_uci(move_uci)
                if move not in board.legal_moves:
                    raise RuntimeError(f"teacher emitted illegal {move_uci} for {state.fen}")
                key = fen4(state.fen)
                entry = {
                    "move": move_uci,
                    "score": score,
                    "teacher_depth": args.our_depth,
                    "origin": state.origin,
                    "tree_ply": ply,
                }
                old = book.get(key)
                if old is not None and old["move"] != move_uci:
                    raise RuntimeError(f"book collision for {key}: {old['move']} vs {move_uci}")
                book[key] = entry
                board.push(move)
                child = State(board.fen(), state.our_color, state.origin)
                nxt[(child.fen, child.our_color)] = child
            else:
                for move_uci, _score in candidates[: args.opponent_width]:
                    move = chess.Move.from_uci(move_uci)
                    if move not in board.legal_moves:
                        raise RuntimeError(f"teacher emitted illegal {move_uci} for {state.fen}")
                    child_board = board.copy(stack=False)
                    child_board.push(move)
                    child = State(child_board.fen(), state.our_color, state.origin)
                    nxt[(child.fen, child.our_color)] = child
        layer_stats.append({
            "ply": ply,
            "states": len(frontier),
            "our_nodes": len(our_states),
            "opponent_nodes": len(opponent_states),
            "next_states": len(nxt),
            "book_entries": len(book),
        })
        print(json.dumps(layer_stats[-1], sort_keys=True), flush=True)
        frontier = list(nxt.values())
        if not frontier:
            break

    payload = {
        "format": "little-gambit-rust-teacher-book-v1",
        "key": "first four FEN fields",
        "our_teacher_depth": args.our_depth,
        "opponent_teacher_depth": args.opponent_depth,
        "opponent_width": args.opponent_width,
        "tree_plies": args.plies,
        "roots": len(roots),
        "entries": dict(sorted(book.items())),
        "layer_stats": layer_stats,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n")
    print(f"book_entries={len(book)} bytes={args.output.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
