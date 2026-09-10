from __future__ import annotations

import argparse
import csv
import io
import json
import struct
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import chess.polyglot

ENTRY = struct.Struct(">QHHI")


def raw_polyglot_move(board: chess.Board, move: chess.Move) -> int:
    to_sq = move.to_square
    if board.is_castling(move):
        if move.from_square == chess.E1:
            to_sq = chess.H1 if move.to_square == chess.G1 else chess.A1
        elif move.from_square == chess.E8:
            to_sq = chess.H8 if move.to_square == chess.G8 else chess.A8
    promotion = 0 if move.promotion is None else int(move.promotion) - 1
    return int(to_sq) | (int(move.from_square) << 6) | (promotion << 12)


def read_opening_positions(paths: list[Path], min_ply: int, max_ply: int):
    by_key: dict[int, dict] = {}
    lines = 0
    parse_failures = 0
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            for row in reader:
                lines += 1
                pgn = (row.get("pgn") or "").strip()
                if not pgn:
                    continue
                try:
                    game = chess.pgn.read_game(io.StringIO(pgn + " *"))
                    if game is None:
                        parse_failures += 1
                        continue
                    board = game.board()
                    name = row.get("name", "")
                    eco = row.get("eco", "")
                    # Every prefix position is a canonical opening position, not only the named
                    # endpoint. This deliberately handles transpositions and starts that land in
                    # the middle of a known opening line.
                    for move in game.mainline_moves():
                        ply = board.ply()
                        if min_ply <= ply <= max_ply:
                            key = int(chess.polyglot.zobrist_hash(board))
                            rec = by_key.setdefault(
                                key,
                                {
                                    "key": key,
                                    "fen": board.fen(),
                                    "ply": ply,
                                    "names": set(),
                                    "ecos": set(),
                                },
                            )
                            if name:
                                rec["names"].add(name)
                            if eco:
                                rec["ecos"].add(eco)
                        if not board.is_legal(move):
                            parse_failures += 1
                            break
                        board.push(move)
                    ply = board.ply()
                    if min_ply <= ply <= max_ply:
                        key = int(chess.polyglot.zobrist_hash(board))
                        rec = by_key.setdefault(
                            key,
                            {
                                "key": key,
                                "fen": board.fen(),
                                "ply": ply,
                                "names": set(),
                                "ecos": set(),
                            },
                        )
                        if name:
                            rec["names"].add(name)
                        if eco:
                            rec["ecos"].add(eco)
                except Exception:
                    parse_failures += 1
    rows = list(by_key.values())
    rows.sort(key=lambda r: (r["ply"], r["key"]))
    return rows, lines, parse_failures


def clear_hash(engine: chess.engine.SimpleEngine) -> None:
    if "Clear Hash" in engine.options:
        engine.configure({"Clear Hash": None})


def analyse_best(engine: chess.engine.SimpleEngine, board: chess.Board, nodes: int):
    clear_hash(engine)
    info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    pv = info.get("pv", [])
    move = pv[0] if pv else None
    score = info["score"].pov(board.turn).score(mate_score=100_000)
    return move, int(score if score is not None else 0)


def write_book(path: Path, rows: list[dict], move_field: str, require_field: str | None = None):
    entries = []
    for row in rows:
        if require_field is not None and not row.get(require_field, False):
            continue
        move_uci = row.get(move_field)
        if not move_uci:
            continue
        board = chess.Board(row["fen"])
        move = chess.Move.from_uci(move_uci)
        if move not in board.legal_moves:
            continue
        entries.append((row["key"], raw_polyglot_move(board, move), 255, 0))
    entries.sort(key=lambda x: (x[0], x[1]))
    with path.open("wb") as handle:
        for entry in entries:
            handle.write(ENTRY.pack(*entry))
    return len(entries)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tsv", type=Path, nargs="+", required=True)
    ap.add_argument("--engine", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--min-ply", type=int, default=4)
    ap.add_argument("--max-ply", type=int, default=18)
    ap.add_argument("--shallow-nodes", type=int, default=10_000)
    ap.add_argument("--deep-nodes", type=int, default=80_000)
    args = ap.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    rows, source_lines, parse_failures = read_opening_positions(args.tsv, args.min_ply, args.max_ply)
    print(
        f"canonical_positions={len(rows)} source_lines={source_lines} "
        f"parse_failures={parse_failures}",
        flush=True,
    )

    engine = chess.engine.SimpleEngine.popen_uci(str(args.engine))
    try:
        cfg = {}
        if "Threads" in engine.options:
            cfg["Threads"] = 1
        if "Hash" in engine.options:
            cfg["Hash"] = 128
        if cfg:
            engine.configure(cfg)

        for i, row in enumerate(rows, 1):
            board = chess.Board(row["fen"])
            sm, ss = analyse_best(engine, board, args.shallow_nodes)
            dm, ds = analyse_best(engine, board, args.deep_nodes)
            row["shallow_move"] = sm.uci() if sm is not None else ""
            row["deep_move"] = dm.uci() if dm is not None else ""
            row["shallow_score"] = ss
            row["deep_score"] = ds
            # DIRECT is deliberately stricter than ordinary opening-book use: require the best
            # move to survive a large node-budget jump with a cleared hash. Unstable positions
            # remain usable as root PRIOR via the deep move, but are not played instantly.
            row["stable_direct"] = bool(sm is not None and dm is not None and sm == dm)
            if i % 250 == 0 or i == len(rows):
                stable = sum(bool(r.get("stable_direct")) for r in rows[:i])
                print(f"analysed={i}/{len(rows)} stable={stable}", flush=True)
    finally:
        engine.quit()

    prior_n = write_book(out / "eco-sf19-prior.bin", rows, "deep_move")
    direct_n = write_book(
        out / "eco-sf19-stable-direct.bin", rows, "deep_move", require_field="stable_direct"
    )

    with (out / "atlas.jsonl").open("w", encoding="utf-8") as handle:
        for row in rows:
            serial = dict(row)
            serial["key_hex"] = f"{int(row['key']):016x}"
            serial["names"] = sorted(row["names"])
            serial["ecos"] = sorted(row["ecos"])
            handle.write(json.dumps(serial, sort_keys=True) + "\n")

    summary = {
        "source_lines": source_lines,
        "parse_failures": parse_failures,
        "canonical_positions": len(rows),
        "prior_entries": prior_n,
        "stable_direct_entries": direct_n,
        "stable_fraction": direct_n / len(rows) if rows else 0.0,
        "min_ply": args.min_ply,
        "max_ply": args.max_ply,
        "shallow_nodes": args.shallow_nodes,
        "deep_nodes": args.deep_nodes,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
