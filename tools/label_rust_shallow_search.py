#!/usr/bin/env python3
"""Label search-distribution FENs with deterministic shallow Rust V15 search scores.

The input is the existing decision corpus. We retain its split/kind metadata, deterministically thin
it without looking at labels, clear Rust search memory before every root, and record the root score
from a fixed-node Gestalt search. This makes the teacher target search-aware while keeping data
provenance and train/validation/holdout separation intact.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import defaultdict
from pathlib import Path


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--rust-bin", required=True)
    p.add_argument("--gestalt", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--nodes", type=int, default=1500)
    p.add_argument("--max-records", type=int, default=36000)
    return p.parse_args()


class Uci:
    def __init__(self, binary: str, gestalt: str) -> None:
        env = os.environ.copy()
        env["CHESS_GESTALT_NETWORK"] = gestalt
        self.p = subprocess.Popen(
            [binary], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1, env=env
        )
        assert self.p.stdin is not None and self.p.stdout is not None
        self.send("uci")
        self.wait("uciok")
        self.send("setoption name Hash value 32")
        self.send("isready")
        self.wait("readyok")

    def send(self, line: str) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def wait(self, prefix: str) -> str:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            line = line.rstrip("\n")
            if line.startswith(prefix):
                return line
        raise RuntimeError(f"Rust UCI exited while waiting for {prefix!r}")

    def score(self, fen: str, nodes: int) -> tuple[int | None, str, int | None]:
        # A fresh TT makes every label depend only on the root, network and fixed node budget.
        self.send("ucinewgame")
        self.send("position fen " + fen)
        self.send(f"go nodes {nodes}")
        info: str | None = None
        assert self.p.stdout is not None
        for line in self.p.stdout:
            line = line.rstrip("\n")
            if line.startswith("info "):
                info = line
            elif line.startswith("bestmove "):
                break
        else:
            raise RuntimeError("Rust UCI exited during shallow label search")
        if info is None:
            raise RuntimeError("search returned no info line")
        fields = info.split()
        try:
            i = fields.index("score")
            kind = fields[i + 1]
            value = int(fields[i + 2])
            n = int(fields[fields.index("nodes") + 1]) if "nodes" in fields else None
        except (ValueError, IndexError) as exc:
            raise RuntimeError(f"cannot parse info line: {info}") from exc
        if kind == "cp":
            return value, kind, n
        if kind == "mate":
            return None, kind, n
        raise RuntimeError(f"unknown UCI score kind {kind!r}")

    def close(self) -> None:
        if self.p.poll() is None:
            self.send("quit")
            self.p.wait(timeout=5)


def thin(rows: list[dict], maximum: int) -> list[dict]:
    # Deduplicate FENs first, preserving first provenance. Then sample each (split,kind) stratum at
    # an approximately equal deterministic frequency so qsearch stand-pat records cannot swamp RFP.
    seen: set[str] = set()
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        fen = str(row["fen"])
        if fen in seen:
            continue
        seen.add(fen)
        groups[(str(row.get("split", "train")), str(row.get("kind", "unknown")))].append(row)
    if len(seen) <= maximum:
        return [row for key in sorted(groups) for row in groups[key]]

    keys = sorted(groups)
    quota = max(1, maximum // len(keys))
    picked: list[dict] = []
    leftovers: list[dict] = []
    for key in keys:
        g = groups[key]
        take = min(quota, len(g))
        if take:
            step = len(g) / take
            indices = {min(len(g) - 1, int(i * step)) for i in range(take)}
            chosen = [g[i] for i in sorted(indices)]
            picked.extend(chosen)
            chosen_fens = {str(r["fen"]) for r in chosen}
            leftovers.extend(r for r in g if str(r["fen"]) not in chosen_fens)
    if len(picked) < maximum:
        remaining = maximum - len(picked)
        if leftovers:
            step = len(leftovers) / min(remaining, len(leftovers))
            picked.extend(leftovers[min(len(leftovers) - 1, int(i * step))] for i in range(min(remaining, len(leftovers))))
    return picked[:maximum]


def main() -> int:
    a = parse_args()
    if a.nodes <= 0 or a.max_records <= 0:
        raise SystemExit("--nodes and --max-records must be positive")
    rows = [json.loads(x) for x in a.input.read_text().splitlines() if x.strip()]
    selected = thin(rows, a.max_records)
    print(json.dumps({"input_records": len(rows), "selected": len(selected), "nodes": a.nodes}), flush=True)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    uci = Uci(a.rust_bin, a.gestalt)
    usable = 0
    mates = 0
    try:
        with a.output.open("w") as out:
            for i, row in enumerate(selected, 1):
                cp, score_kind, actual_nodes = uci.score(str(row["fen"]), a.nodes)
                if cp is None:
                    mates += 1
                else:
                    record = dict(row)
                    record["gestalt_static_cp"] = record.pop("teacher_cp", None)
                    record["rust_search_cp"] = cp
                    record["rust_search_nodes"] = actual_nodes
                    record["rust_search_budget"] = a.nodes
                    out.write(json.dumps(record, sort_keys=True) + "\n")
                    usable += 1
                if i % 1000 == 0:
                    print(json.dumps({"labelled": i, "usable": usable, "mates_skipped": mates}), flush=True)
    finally:
        uci.close()
    print("FINAL " + json.dumps({"selected": len(selected), "usable": usable, "mates_skipped": mates, "nodes": a.nodes}, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
