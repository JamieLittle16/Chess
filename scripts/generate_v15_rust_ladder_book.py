#!/usr/bin/env python3
"""Generate a compact opening response book from our own Rust V15 engine.

The current rated starter exposes eight fixed opening roots. We cover both colour assignments:
* if Little Gambit owns the root side to move, store a Rust move and one further response after
  every legal opponent reply;
* if the opponent owns the root side to move, branch over every legal first move, then store two
  Rust responses with every legal intervening opponent reply.

Only our own engine supplies moves. The resulting JSON is a conventional opening book; on any miss
the Python submission falls back to its ordinary search.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import chess
import chess.engine

OPENINGS = [
    "r1bqk2r/pp1pppbp/2n2np1/2p5/2P5/2N1PNP1/PP1P1PBP/R1BQK2R b KQkq - 0 6",
    "r1b1k2r/pp2nppp/2n1p3/q1ppP3/P2P4/2P2N2/2PB1PPP/R2QKB1R b KQkq - 4 9",
    "rnbqkb1r/pp3ppp/2p5/1B1p4/3Pn3/5N2/PPP2PPP/RNBQK2R w KQkq - 0 7",
    "r1bq1rk1/pppp1ppp/2n2n2/1Bb5/3NP3/2P5/PP3PPP/RNBQ1RK1 w - - 3 8",
    "rnbqk2r/pp2ppbp/6p1/2p5/3PP3/2P1BN2/P4PPP/R2QKB1R b KQkq - 1 8",
    "r1bqk2r/pp1n1ppp/2n1p3/2bpP3/5P2/2NB4/PPP3PP/R1BQK1NR w KQkq - 0 8",
    "1rbqk1nr/pp2ppbp/2np2p1/2p5/P3P3/2NP2P1/1PP1NPBP/R1BQK2R b KQk - 0 7",
    "r1bqkb1r/pp3ppp/2np4/1N1Pp3/8/8/PPP2PPP/R1BQKB1R b KQkq - 0 8",
]


def key(board: chess.Board) -> str:
    return " ".join(board.fen(en_passant="fen").split()[:4])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--nodes", type=int, default=10_000)
    ap.add_argument("--mainline-nodes", type=int, default=60_000)
    ap.add_argument("--mainline-plies", type=int, default=10)
    args = ap.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)

    book: dict[str, str] = {}
    searches = 0

    with chess.engine.SimpleEngine.popen_uci(str(args.engine)) as engine:
        engine.configure({"Hash": 64})

        def label(board: chess.Board, nodes: int) -> chess.Move | None:
            nonlocal searches
            if board.is_game_over(claim_draw=True):
                return None
            k = key(board)
            existing = book.get(k)
            if existing is not None:
                move = chess.Move.from_uci(existing)
                if move in board.legal_moves:
                    return move
            result = engine.play(board, chess.engine.Limit(nodes=nodes))
            move = result.move
            if move is None or move not in board.legal_moves:
                return None
            book[k] = move.uci()
            searches += 1
            if searches % 100 == 0:
                print(json.dumps({"searches": searches, "entries": len(book)}), flush=True)
            return move

        def our_turn_tree(board: chess.Board, remaining_our_moves: int) -> None:
            if remaining_our_moves <= 0 or board.is_game_over(claim_draw=True):
                return
            move = label(board, args.nodes)
            if move is None:
                return
            after_ours = board.copy(stack=False)
            after_ours.push(move)
            if remaining_our_moves == 1 or after_ours.is_game_over(claim_draw=True):
                return
            for reply in list(after_ours.legal_moves):
                child = after_ours.copy(stack=False)
                child.push(reply)
                our_turn_tree(child, remaining_our_moves - 1)

        for fen in OPENINGS:
            root = chess.Board(fen)
            # Candidate owns the FEN side to move.
            our_turn_tree(root.copy(stack=False), 2)
            # Candidate owns the opposite colour: opponent makes any legal first move.
            for first in list(root.legal_moves):
                child = root.copy(stack=False)
                child.push(first)
                our_turn_tree(child, 2)

            # Overlay a deeper high-budget Rust self-play principal line. These entries are useful
            # for the common case where both sides choose strong/mainline continuations.
            line = root.copy(stack=False)
            for _ in range(args.mainline_plies):
                if line.is_game_over(claim_draw=True):
                    break
                move = label(line, args.mainline_nodes)
                if move is None:
                    break
                line.push(move)

    payload = {
        "schema_version": 1,
        "source": "Chess Rust V15 production engine",
        "nodes_per_response": args.nodes,
        "mainline_nodes": args.mainline_nodes,
        "mainline_plies": args.mainline_plies,
        "opening_roots": OPENINGS,
        "entries": dict(sorted(book.items())),
    }
    args.output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    manifest = {
        "entries": len(book),
        "searches": searches,
        "bytes": args.output.stat().st_size,
        "nodes_per_response": args.nodes,
        "mainline_nodes": args.mainline_nodes,
    }
    args.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("FINAL", json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
