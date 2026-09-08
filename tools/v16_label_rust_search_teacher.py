#!/usr/bin/env python3
"""Label a frozen FEN corpus with deterministic Rust V15 fixed-depth search scores."""
from __future__ import annotations

import argparse
import json
import os
import queue
import subprocess
import threading
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--network", type=Path, required=True)
    p.add_argument("--depth", type=int, default=4)
    p.add_argument("--train", type=int, default=18000)
    p.add_argument("--validation", type=int, default=3000)
    p.add_argument("--holdout", type=int, default=3000)
    return p.parse_args()


class Uci:
    def __init__(self, engine: Path, network: Path) -> None:
        env = os.environ.copy()
        env["CHESS_GESTALT_NETWORK"] = str(network.resolve())
        self.p = subprocess.Popen(
            [str(engine.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self.p.stdin is not None and self.p.stdout is not None
        self.q: queue.Queue[str | None] = queue.Queue()
        def pump() -> None:
            assert self.p.stdout is not None
            for line in self.p.stdout:
                self.q.put(line.rstrip("\n"))
            self.q.put(None)
        threading.Thread(target=pump, daemon=True).start()
        self.send("uci")
        self.wait("uciok", 10.0)
        self.send("setoption name Hash value 16")
        self.send("isready")
        self.wait("readyok", 10.0)

    def send(self, line: str) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def wait(self, prefix: str, timeout: float) -> str:
        while True:
            line = self.q.get(timeout=timeout)
            if line is None:
                raise RuntimeError(f"engine exited: {self.p.poll()}")
            if line.startswith(prefix):
                return line

    def search(self, fen: str, depth: int) -> tuple[int | None, int | None, str, int]:
        self.send("ucinewgame")
        self.send("position fen " + fen)
        self.send(f"go depth {depth}")
        score_cp: int | None = None
        score_mate: int | None = None
        nodes = 0
        while True:
            line = self.q.get(timeout=30.0)
            if line is None:
                raise RuntimeError(f"engine exited: {self.p.poll()}")
            if line.startswith("info "):
                fields = line.split()
                try:
                    i = fields.index("score")
                    kind, value = fields[i + 1], int(fields[i + 2])
                    if kind == "cp":
                        score_cp, score_mate = value, None
                    elif kind == "mate":
                        score_mate, score_cp = value, None
                except (ValueError, IndexError):
                    pass
                try:
                    nodes = int(fields[fields.index("nodes") + 1])
                except (ValueError, IndexError):
                    pass
            elif line.startswith("bestmove "):
                move = line.split()[1]
                if score_cp is None and score_mate is None:
                    raise RuntimeError(f"missing score before {line!r}")
                return score_cp, score_mate, move, nodes

    def close(self) -> None:
        if self.p.poll() is None:
            try:
                self.send("quit")
                self.p.wait(timeout=2)
            except Exception:
                self.p.kill()
                self.p.wait()


def stable_select(rows: list[dict[str, object]], split: str, count: int) -> list[dict[str, object]]:
    import hashlib
    candidates = [r for r in rows if r.get("split") == split]
    candidates.sort(key=lambda r: hashlib.sha256(("v16-search-teacher|" + str(r["fen"])).encode()).digest())
    if len(candidates) < count:
        raise SystemExit(f"need {count} {split} rows, have {len(candidates)}")
    return candidates[:count]


def main() -> int:
    a = parse_args()
    rows = [json.loads(line) for line in a.input.read_text().splitlines() if line.strip()]
    selected = (
        stable_select(rows, "train", a.train)
        + stable_select(rows, "validation", a.validation)
        + stable_select(rows, "holdout", a.holdout)
    )
    engine = Uci(a.engine, a.network)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    counts = {"train": 0, "validation": 0, "holdout": 0}
    cp_values: list[int] = []
    mate_count = 0
    total_nodes = 0
    try:
        with a.output.open("w") as out:
            for index, row in enumerate(selected, 1):
                cp, mate, move, nodes = engine.search(str(row["fen"]), a.depth)
                labelled = dict(row)
                labelled["static_gestalt_cp"] = row.get("teacher_cp")
                labelled["teacher_cp"] = 0 if cp is None else cp
                labelled["teacher_mate"] = mate
                labelled["teacher_bestmove"] = move
                labelled["teacher_depth"] = a.depth
                labelled["teacher_nodes"] = nodes
                out.write(json.dumps(labelled, separators=(",", ":")) + "\n")
                counts[str(row["split"])] += 1
                total_nodes += nodes
                if cp is None:
                    mate_count += 1
                else:
                    cp_values.append(cp)
                if index % 1000 == 0:
                    print(json.dumps({"labelled": index, "counts": counts, "mates": mate_count, "nodes": total_nodes}), flush=True)
    finally:
        engine.close()
    summary = {
        "records": len(selected),
        "depth": a.depth,
        "counts": counts,
        "mates": mate_count,
        "mean_abs_cp": sum(abs(x) for x in cp_values) / max(1, len(cp_values)),
        "max_abs_cp": max((abs(x) for x in cp_values), default=0),
        "total_search_nodes": total_nodes,
    }
    print("FINAL", json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
