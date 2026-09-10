from __future__ import annotations

import argparse
import csv
import json
import time
from collections import deque
from pathlib import Path

import chess
import chess.engine
import chess.polyglot


def cp_value(score: chess.engine.PovScore, turn: chess.Color) -> int:
    value = score.pov(turn).score(mate_score=100_000)
    return int(value if value is not None else 0)


def legal_entries(reader: chess.polyglot.MemoryMappedReader, board: chess.Board):
    legal = set(board.legal_moves)
    entries = []
    for entry in reader.find_all(board):
        if entry.move in legal and int(entry.weight) > 0:
            entries.append(entry)
    entries.sort(key=lambda entry: (-int(entry.weight), entry.move.uci()))
    return entries


def current_direct_gate(top_weight: int, total_weight: int) -> bool:
    if top_weight < 16 or total_weight <= 0:
        return False
    share = top_weight / total_weight
    return share >= 0.70 or (top_weight >= 96 and share >= 0.60)


def analyse_once(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    book_move: chess.Move,
    nodes: int,
) -> tuple[str, int, int, int]:
    if "Clear Hash" in engine.options:
        engine.configure({"Clear Hash": None})
    best = engine.analyse(board, chess.engine.Limit(nodes=nodes))
    best_move = best.get("pv", [None])[0]
    best_cp = cp_value(best["score"], board.turn)

    if "Clear Hash" in engine.options:
        engine.configure({"Clear Hash": None})
    forced = engine.analyse(
        board,
        chess.engine.Limit(nodes=nodes),
        root_moves=[book_move],
    )
    book_cp = cp_value(forced["score"], board.turn)
    loss = max(0, best_cp - book_cp)
    return (best_move.uci() if best_move is not None else "", best_cp, book_cp, loss)


def enumerate_book(reader: chess.polyglot.MemoryMappedReader, max_ply: int):
    queue: deque[chess.Board] = deque([chess.Board()])
    seen: set[int] = set()
    rows = []
    while queue:
        board = queue.popleft()
        if board.ply() > max_ply:
            continue
        key = int(chess.polyglot.zobrist_hash(board))
        if key in seen:
            continue
        seen.add(key)
        entries = legal_entries(reader, board)
        if not entries:
            continue
        total_weight = sum(int(entry.weight) for entry in entries)
        top = entries[0]
        rows.append(
            {
                "key": key,
                "key_hex": f"{key:016x}",
                "ply": board.ply(),
                "fen": board.fen(),
                "book_move": top.move.uci(),
                "top_weight": int(top.weight),
                "total_weight": total_weight,
                "share": int(top.weight) / total_weight,
                "move_count": len(entries),
                "current_direct": current_direct_gate(int(top.weight), total_weight),
            }
        )
        if board.ply() < max_ply:
            for entry in entries:
                child = board.copy(stack=False)
                child.push(entry.move)
                queue.append(child)
    rows.sort(key=lambda row: (int(row["ply"]), str(row["key_hex"])))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--max-ply", type=int, default=18)
    parser.add_argument("--shallow-nodes", type=int, default=20_000)
    parser.add_argument("--deep-nodes", type=int, default=120_000)
    parser.add_argument("--min-audit-weight", type=int, default=4)
    args = parser.parse_args()

    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()

    with chess.polyglot.open_reader(args.book) as reader:
        inventory = enumerate_book(reader, args.max_ply)

    inventory_fields = [
        "key_hex", "ply", "fen", "book_move", "top_weight", "total_weight",
        "share", "move_count", "current_direct"
    ]
    with (out / "inventory.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory_fields)
        writer.writeheader()
        for row in inventory:
            writer.writerow({field: row[field] for field in inventory_fields})

    candidates = [row for row in inventory if int(row["top_weight"]) >= args.min_audit_weight]
    engine = chess.engine.SimpleEngine.popen_uci(str(args.engine))
    try:
        config = {}
        if "Threads" in engine.options:
            config["Threads"] = 1
        if "Hash" in engine.options:
            config["Hash"] = 128
        if config:
            engine.configure(config)

        audit_rows = []
        for index, row in enumerate(candidates, start=1):
            board = chess.Board(str(row["fen"]))
            book_move = chess.Move.from_uci(str(row["book_move"]))
            shallow_best, shallow_best_cp, shallow_book_cp, shallow_loss = analyse_once(
                engine, board, book_move, args.shallow_nodes
            )

            # Deep-check every move already eligible for DIRECT. For possible expansion entries,
            # spend the larger analysis only when the first pass is already close enough to be
            # realistically admissible. This keeps the audit broad without wasting runner time on
            # obviously inferior continuations.
            needs_deep = bool(row["current_direct"]) or (
                int(row["top_weight"]) >= 8 and shallow_loss <= 16
            ) or (
                int(row["top_weight"]) >= 4 and shallow_best == str(row["book_move"])
            )

            deep_best = ""
            deep_best_cp = shallow_best_cp
            deep_book_cp = shallow_book_cp
            deep_loss = shallow_loss
            if needs_deep:
                deep_best, deep_best_cp, deep_book_cp, deep_loss = analyse_once(
                    engine, board, book_move, args.deep_nodes
                )

            # Conservative outputs, intentionally separated into a blacklist and an expansion
            # whitelist. The production engine can keep its current proven DIRECT gate while only
            # suppressing clearly bad audited hits and adding exceptionally clean new ones.
            blacklist = bool(row["current_direct"]) and needs_deep and deep_loss > 20
            expansion = (not bool(row["current_direct"])) and needs_deep and (
                (
                    int(row["top_weight"]) >= 8
                    and shallow_loss <= 8
                    and deep_loss <= 8
                )
                or (
                    int(row["top_weight"]) >= 4
                    and shallow_best == str(row["book_move"])
                    and deep_best == str(row["book_move"])
                    and deep_loss <= 4
                )
            )

            result = dict(row)
            result.update(
                shallow_best=shallow_best,
                shallow_best_cp=shallow_best_cp,
                shallow_book_cp=shallow_book_cp,
                shallow_loss=shallow_loss,
                deep_checked=needs_deep,
                deep_best=deep_best,
                deep_best_cp=deep_best_cp,
                deep_book_cp=deep_book_cp,
                deep_loss=deep_loss,
                blacklist=blacklist,
                expansion=expansion,
            )
            audit_rows.append(result)

            if index % 100 == 0 or index == len(candidates):
                elapsed = time.monotonic() - started
                print(
                    f"audited {index}/{len(candidates)} positions in {elapsed:.1f}s; "
                    f"blacklist={sum(bool(r['blacklist']) for r in audit_rows)} "
                    f"expansion={sum(bool(r['expansion']) for r in audit_rows)}",
                    flush=True,
                )
                # Preserve useful partial evidence even if a runner is interrupted later.
                with (out / "audit.partial.jsonl").open("w") as handle:
                    for item in audit_rows:
                        handle.write(json.dumps(item, sort_keys=True) + "\n")
    finally:
        engine.quit()

    audit_fields = inventory_fields + [
        "shallow_best", "shallow_best_cp", "shallow_book_cp", "shallow_loss",
        "deep_checked", "deep_best", "deep_best_cp", "deep_book_cp", "deep_loss",
        "blacklist", "expansion"
    ]
    with (out / "audit.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=audit_fields)
        writer.writeheader()
        for row in audit_rows:
            writer.writerow({field: row[field] for field in audit_fields})

    blacklisted = [row for row in audit_rows if bool(row["blacklist"])]
    expanded = [row for row in audit_rows if bool(row["expansion"])]
    (out / "blacklist_keys.txt").write_text(
        "".join(f"{row['key_hex']} {row['book_move']} {row['deep_loss']}\n" for row in blacklisted)
    )
    (out / "expansion_keys.txt").write_text(
        "".join(f"{row['key_hex']} {row['book_move']} {row['deep_loss']}\n" for row in expanded)
    )

    current = [row for row in audit_rows if bool(row["current_direct"])]
    summary = {
        "inventory_positions": len(inventory),
        "audited_positions": len(audit_rows),
        "current_direct_positions": len(current),
        "current_direct_blacklist": len(blacklisted),
        "expansion_whitelist": len(expanded),
        "current_direct_mean_deep_loss": (
            sum(int(row["deep_loss"]) for row in current) / len(current) if current else None
        ),
        "current_direct_max_deep_loss": max((int(row["deep_loss"]) for row in current), default=None),
        "elapsed_s": time.monotonic() - started,
        "shallow_nodes": args.shallow_nodes,
        "deep_nodes": args.deep_nodes,
        "max_ply": args.max_ply,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
