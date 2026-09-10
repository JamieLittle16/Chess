from __future__ import annotations

import argparse
import csv
import io
import struct
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import chess.polyglot
import zstandard as zstd

ENTRY = struct.Struct(">QHHI")


@dataclass
class PositionStat:
    fen: str
    ply: int
    move_counts: dict[str, int]


def raw_polyglot_move(board: chess.Board, move: chess.Move) -> int:
    to_sq = move.to_square
    if board.is_castling(move):
        if move.from_square == chess.E1:
            to_sq = chess.H1 if move.to_square == chess.G1 else chess.A1
        elif move.from_square == chess.E8:
            to_sq = chess.H8 if move.to_square == chess.G8 else chess.A8
    promotion = 0 if move.promotion is None else int(move.promotion) - 1
    return int(to_sq) | (int(move.from_square) << 6) | (promotion << 12)


def collect(paths: list[Path], max_ply: int) -> dict[int, PositionStat]:
    stats: dict[int, PositionStat] = {}
    games = 0
    dctx = zstd.ZstdDecompressor()
    for path in paths:
        with path.open("rb") as raw, dctx.stream_reader(raw) as zr:
            text = io.TextIOWrapper(zr, encoding="utf-8", errors="replace")
            while True:
                try:
                    game = chess.pgn.read_game(text)
                except Exception as exc:
                    print(f"PGN parse warning: {exc}", flush=True)
                    continue
                if game is None:
                    break
                games += 1
                board = game.board()
                for move in game.mainline_moves():
                    if board.ply() > max_ply:
                        break
                    if board.chess960 or not board.is_legal(move):
                        break
                    key = int(chess.polyglot.zobrist_hash(board))
                    stat = stats.get(key)
                    if stat is None:
                        stat = PositionStat(board.fen(), board.ply(), {})
                        stats[key] = stat
                    else:
                        stat.ply = min(stat.ply, board.ply())
                    uci = move.uci()
                    stat.move_counts[uci] = stat.move_counts.get(uci, 0) + 1
                    board.push(move)
                if games % 10_000 == 0:
                    print(f"collect games={games} positions={len(stats)}", flush=True)
    print(f"COLLECTED games={games} positions={len(stats)}", flush=True)
    return stats


def cp(score: chess.engine.PovScore, turn: chess.Color) -> int:
    value = score.pov(turn).score(mate_score=100_000)
    return int(value if value is not None else 0)


def clear_hash(engine: chess.engine.SimpleEngine) -> None:
    if "Clear Hash" in engine.options:
        engine.configure({"Clear Hash": None})


def analyse(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    move: chess.Move,
    nodes: int,
) -> tuple[str, int, int, int]:
    clear_hash(engine)
    best = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    pv = best.get("pv", [])
    best_move = pv[0].uci() if pv else ""
    best_cp = cp(best["score"], board.turn)

    clear_hash(engine)
    forced = engine.analyse(board, chess.engine.Limit(nodes=nodes), root_moves=[move])
    move_cp = cp(forced["score"], board.turn)
    loss = max(0, best_cp - move_cp)
    return best_move, best_cp, move_cp, loss


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, nargs="+", required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--max-ply", type=int, default=18)
    p.add_argument("--min-top-count", type=int, default=3)
    p.add_argument("--min-share", type=float, default=0.55)
    p.add_argument("--max-candidates", type=int, default=20_000)
    p.add_argument("--shallow-nodes", type=int, default=8_000)
    p.add_argument("--deep-nodes", type=int, default=80_000)
    p.add_argument("--max-loss-cp", type=int, default=8)
    args = p.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    stats = collect(list(args.input), args.max_ply)

    candidates: list[tuple[int, PositionStat, str, int, int, float]] = []
    for key, stat in stats.items():
        total = sum(stat.move_counts.values())
        top_uci, top_count = sorted(stat.move_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
        share = top_count / total
        if top_count >= args.min_top_count and share >= args.min_share:
            candidates.append((key, stat, top_uci, top_count, total, share))

    # Prioritize well-observed consensus positions, but retain ply as a weak tiebreak so the
    # competition's usual mid-opening starts receive certification before move-one trivia.
    candidates.sort(key=lambda row: (-row[3], -row[5], -row[1].ply, row[0]))
    candidates = candidates[: args.max_candidates]
    print(
        f"CANDIDATES selected={len(candidates)} min_top={args.min_top_count} "
        f"min_share={args.min_share:.3f}",
        flush=True,
    )

    engine = chess.engine.SimpleEngine.popen_uci(str(args.engine))
    config = {}
    if "Threads" in engine.options:
        config["Threads"] = 1
    if "Hash" in engine.options:
        config["Hash"] = 128
    if config:
        engine.configure(config)

    certified: list[tuple[int, int, int, int]] = []
    rows: list[dict[str, object]] = []
    started = time.monotonic()
    try:
        for idx, (key, stat, top_uci, top_count, total, share) in enumerate(candidates, start=1):
            board = chess.Board(stat.fen)
            move = chess.Move.from_uci(top_uci)
            if move not in board.legal_moves:
                continue
            sb, sbcp, smcp, sloss = analyse(engine, board, move, args.shallow_nodes)

            deep_checked = sloss <= args.max_loss_cp + 4
            db = ""
            dbcp = sbcp
            dmcp = smcp
            dloss = sloss
            if deep_checked:
                db, dbcp, dmcp, dloss = analyse(engine, board, move, args.deep_nodes)

            ok = deep_checked and sloss <= args.max_loss_cp and dloss <= args.max_loss_cp
            if ok:
                certified.append((key, raw_polyglot_move(board, move), 65535, 0))

            rows.append(
                {
                    "key_hex": f"{key:016x}",
                    "ply": stat.ply,
                    "fen": stat.fen,
                    "move": top_uci,
                    "top_count": top_count,
                    "total_count": total,
                    "share": f"{share:.6f}",
                    "shallow_best": sb,
                    "shallow_best_cp": sbcp,
                    "shallow_move_cp": smcp,
                    "shallow_loss": sloss,
                    "deep_checked": deep_checked,
                    "deep_best": db,
                    "deep_best_cp": dbcp,
                    "deep_move_cp": dmcp,
                    "deep_loss": dloss,
                    "certified": ok,
                }
            )
            if idx % 250 == 0 or idx == len(candidates):
                print(
                    f"audit {idx}/{len(candidates)} certified={len(certified)} "
                    f"elapsed={time.monotonic()-started:.1f}s",
                    flush=True,
                )
    finally:
        engine.quit()

    certified.sort(key=lambda row: (row[0], row[1]))
    with (out / "broadcast-sf19-certified.bin").open("wb") as f:
        for row in certified:
            f.write(ENTRY.pack(*row))

    fields = [
        "key_hex", "ply", "fen", "move", "top_count", "total_count", "share",
        "shallow_best", "shallow_best_cp", "shallow_move_cp", "shallow_loss",
        "deep_checked", "deep_best", "deep_best_cp", "deep_move_cp", "deep_loss", "certified",
    ]
    with (out / "audit.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    print(
        f"DONE candidates={len(candidates)} certified={len(certified)} "
        f"cert_bytes={(out/'broadcast-sf19-certified.bin').stat().st_size} "
        f"elapsed={time.monotonic()-started:.1f}s",
        flush=True,
    )


if __name__ == "__main__":
    main()
