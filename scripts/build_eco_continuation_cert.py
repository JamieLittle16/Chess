from __future__ import annotations

import argparse
import csv
import io
import json
import struct
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import chess.polyglot

ENTRY = struct.Struct(">QHHI")


@dataclass
class Stat:
    fen: str
    ply: int
    moves: dict[str, int]
    names: set[str]
    ecos: set[str]


def raw_polyglot_move(board: chess.Board, move: chess.Move) -> int:
    to_sq = move.to_square
    if board.is_castling(move):
        if move.from_square == chess.E1:
            to_sq = chess.H1 if move.to_square == chess.G1 else chess.A1
        elif move.from_square == chess.E8:
            to_sq = chess.H8 if move.to_square == chess.G8 else chess.A8
    promotion = 0 if move.promotion is None else int(move.promotion) - 1
    return int(to_sq) | (int(move.from_square) << 6) | (promotion << 12)


def collect(paths: list[Path], min_ply: int, max_ply: int) -> tuple[dict[int, Stat], int, int]:
    stats: dict[int, Stat] = {}
    lines = 0
    failures = 0
    for path in paths:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                lines += 1
                pgn = (row.get("pgn") or "").strip()
                if not pgn:
                    continue
                try:
                    game = chess.pgn.read_game(io.StringIO(pgn + " *"))
                    if game is None:
                        failures += 1
                        continue
                    board = game.board()
                    for move in game.mainline_moves():
                        ply = board.ply()
                        if min_ply <= ply <= max_ply and board.is_legal(move):
                            key = int(chess.polyglot.zobrist_hash(board))
                            stat = stats.get(key)
                            if stat is None:
                                stat = Stat(board.fen(), ply, {}, set(), set())
                                stats[key] = stat
                            stat.moves[move.uci()] = stat.moves.get(move.uci(), 0) + 1
                            name = row.get("name", "")
                            eco = row.get("eco", "")
                            if name:
                                stat.names.add(name)
                            if eco:
                                stat.ecos.add(eco)
                        if not board.is_legal(move):
                            failures += 1
                            break
                        board.push(move)
                except Exception:
                    failures += 1
    return stats, lines, failures


def cp(score: chess.engine.PovScore, turn: chess.Color) -> int:
    value = score.pov(turn).score(mate_score=100_000)
    return int(value if value is not None else 0)


def clear_hash(engine: chess.engine.SimpleEngine) -> None:
    if "Clear Hash" in engine.options:
        engine.configure({"Clear Hash": None})


def analyse(engine: chess.engine.SimpleEngine, board: chess.Board, move: chess.Move, nodes: int):
    clear_hash(engine)
    best = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    best_move = best.get("pv", [None])[0]
    best_cp = cp(best["score"], board.turn)
    clear_hash(engine)
    forced = engine.analyse(board, chess.engine.Limit(nodes=nodes), root_moves=[move])
    move_cp = cp(forced["score"], board.turn)
    return (best_move.uci() if best_move else "", best_cp, move_cp, max(0, best_cp - move_cp))


def write(path: Path, rows: list[dict], certified_only: bool) -> int:
    entries = []
    for row in rows:
        if certified_only and not row["certified"]:
            continue
        board = chess.Board(row["fen"])
        move = chess.Move.from_uci(row["move"])
        if move not in board.legal_moves:
            continue
        weight = 65535 if certified_only else min(65535, max(1, int(row["top_count"])))
        entries.append((int(row["key"]), raw_polyglot_move(board, move), weight, 0))
    entries.sort(key=lambda x: (x[0], x[1]))
    with path.open("wb") as f:
        for entry in entries:
            f.write(ENTRY.pack(*entry))
    return len(entries)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--tsv", type=Path, nargs="+", required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--min-ply", type=int, default=4)
    p.add_argument("--max-ply", type=int, default=18)
    p.add_argument("--shallow-nodes", type=int, default=8_000)
    p.add_argument("--deep-nodes", type=int, default=60_000)
    p.add_argument("--max-loss-cp", type=int, default=8)
    args = p.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    stats, lines, failures = collect(args.tsv, args.min_ply, args.max_ply)
    candidates = []
    for key, stat in stats.items():
        top_uci, top_count = sorted(stat.moves.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        candidates.append((key, stat, top_uci, top_count, sum(stat.moves.values())))
    candidates.sort(key=lambda x: (-x[3], -x[4], -x[1].ply, x[0]))
    print(f"source_lines={lines} failures={failures} candidate_positions={len(candidates)}", flush=True)

    engine = chess.engine.SimpleEngine.popen_uci(str(args.engine))
    config = {}
    if "Threads" in engine.options:
        config["Threads"] = 1
    if "Hash" in engine.options:
        config["Hash"] = 128
    if config:
        engine.configure(config)

    rows: list[dict] = []
    try:
        for i, (key, stat, uci, top_count, total_count) in enumerate(candidates, 1):
            board = chess.Board(stat.fen)
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                continue
            sb, sbcp, smcp, sloss = analyse(engine, board, move, args.shallow_nodes)
            deep_checked = sloss <= args.max_loss_cp + 4
            db, dbcp, dmcp, dloss = sb, sbcp, smcp, sloss
            if deep_checked:
                db, dbcp, dmcp, dloss = analyse(engine, board, move, args.deep_nodes)
            certified = deep_checked and sloss <= args.max_loss_cp and dloss <= args.max_loss_cp
            rows.append({
                "key": key,
                "key_hex": f"{key:016x}",
                "fen": stat.fen,
                "ply": stat.ply,
                "move": uci,
                "top_count": top_count,
                "total_count": total_count,
                "share": top_count / total_count,
                "names": sorted(stat.names),
                "ecos": sorted(stat.ecos),
                "shallow_best": sb,
                "shallow_best_cp": sbcp,
                "shallow_move_cp": smcp,
                "shallow_loss": sloss,
                "deep_checked": deep_checked,
                "deep_best": db,
                "deep_best_cp": dbcp,
                "deep_move_cp": dmcp,
                "deep_loss": dloss,
                "certified": certified,
            })
            if i % 250 == 0 or i == len(candidates):
                print(f"audit {i}/{len(candidates)} certified={sum(bool(r['certified']) for r in rows)}", flush=True)
    finally:
        engine.quit()

    prior_n = write(out / "eco-curated-prior.bin", rows, False)
    direct_n = write(out / "eco-curated-sf19-direct.bin", rows, True)
    with (out / "audit.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    summary = {
        "source_lines": lines,
        "parse_failures": failures,
        "candidate_positions": len(candidates),
        "prior_entries": prior_n,
        "certified_direct_entries": direct_n,
        "certified_fraction": direct_n / prior_n if prior_n else 0.0,
        "min_ply": args.min_ply,
        "max_ply": args.max_ply,
        "max_loss_cp": args.max_loss_cp,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
