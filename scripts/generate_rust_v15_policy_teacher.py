#!/usr/bin/env python3
"""Label chess positions with the production Rust V15 engine through one persistent UCI process.

The output is intentionally compatible with the Python root-policy trainer: each record contains a
FEN, deterministic train/validation/holdout split, and `teacher_best_move`. A persistent engine keeps
startup/network-load cost out of the per-position path; `ucinewgame` isolates search state between
independent roots.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--network", type=Path, required=True)
    p.add_argument("--epd", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--nodes", type=int, default=15_000)
    p.add_argument("--start", type=int, default=0)
    p.add_argument("--count", type=int, default=None)
    p.add_argument("--hash-mb", type=int, default=32)
    p.add_argument("--split-salt", default="Chess/v15-rust-policy-teacher-v1")
    return p.parse_args()


def normalize_fen(line: str) -> str:
    fields = line.strip().split()
    if len(fields) < 4:
        raise ValueError(f"invalid EPD/FEN line: {line!r}")
    return " ".join(fields[:4]) + " 0 1"


def split_for(fen: str, salt: str) -> str:
    h = hashlib.sha256((salt + "\0" + " ".join(fen.split()[:4])).encode()).digest()
    bucket = int.from_bytes(h[:8], "big") % 1000
    if bucket < 100:
        return "holdout"
    if bucket < 200:
        return "validation"
    return "train"


class UciTeacher:
    def __init__(self, engine: Path, network: Path, hash_mb: int):
        env = os.environ.copy()
        env["CHESS_GESTALT_NETWORK"] = str(network.resolve())
        self.p = subprocess.Popen(
            [str(engine.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
            env=env,
        )
        assert self.p.stdin is not None and self.p.stdout is not None
        self._send("uci")
        self._wait_for("uciok")
        self._send(f"setoption name Hash value {hash_mb}")
        self._send("isready")
        self._wait_for("readyok")

    def _send(self, line: str) -> None:
        assert self.p.stdin is not None
        self.p.stdin.write(line + "\n")
        self.p.stdin.flush()

    def _wait_for(self, target: str) -> None:
        assert self.p.stdout is not None
        for line in self.p.stdout:
            if line.strip() == target:
                return
        raise RuntimeError(f"UCI engine exited waiting for {target}")

    def bestmove(self, fen: str, nodes: int) -> tuple[str, dict[str, object]]:
        self._send("ucinewgame")
        self._send("position fen " + fen)
        self._send(f"go nodes {nodes}")
        last_info: dict[str, object] = {}
        assert self.p.stdout is not None
        for raw in self.p.stdout:
            line = raw.strip()
            if line.startswith("info "):
                parts = line.split()
                for key in ("depth", "seldepth", "nodes", "nps"):
                    if key in parts:
                        try:
                            last_info[key] = int(parts[parts.index(key) + 1])
                        except (ValueError, IndexError):
                            pass
                if "score" in parts:
                    i = parts.index("score")
                    if i + 2 < len(parts):
                        kind = parts[i + 1]
                        try:
                            last_info[f"score_{kind}"] = int(parts[i + 2])
                        except ValueError:
                            pass
            elif line.startswith("bestmove "):
                move = line.split()[1]
                if move == "(none)":
                    raise RuntimeError(f"no bestmove for nonterminal corpus FEN {fen}")
                return move, last_info
        raise RuntimeError("UCI engine exited during search")

    def close(self) -> None:
        if self.p.poll() is None:
            try:
                self._send("quit")
                self.p.wait(timeout=5)
            except Exception:
                self.p.kill()
                self.p.wait(timeout=5)


def main() -> int:
    a = parse_args()
    lines = [x for x in a.epd.read_text().splitlines() if x.strip() and not x.lstrip().startswith("#")]
    end = len(lines) if a.count is None else min(len(lines), a.start + a.count)
    selected = lines[a.start:end]
    if not selected:
        raise SystemExit("empty selected corpus slice")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    teacher = UciTeacher(a.engine, a.network, a.hash_mb)
    counts = {"train": 0, "validation": 0, "holdout": 0}
    started = time.monotonic()
    try:
        with a.output.open("w", encoding="utf-8") as out:
            for local_i, line in enumerate(selected):
                index = a.start + local_i
                fen = normalize_fen(line)
                move, info = teacher.bestmove(fen, a.nodes)
                split = split_for(fen, a.split_salt)
                counts[split] += 1
                record = {
                    "schema_version": 1,
                    "teacher": "LittleGambit Rust V15",
                    "source_index": index,
                    "split": split,
                    "fen": fen,
                    "teacher_best_move": move,
                    "teacher_nodes_budget": a.nodes,
                    **{f"teacher_{k}": v for k, v in info.items()},
                }
                out.write(json.dumps(record, sort_keys=True) + "\n")
                if (local_i + 1) % 100 == 0:
                    elapsed = max(1e-9, time.monotonic() - started)
                    print(json.dumps({"done": local_i + 1, "rate_positions_s": (local_i + 1) / elapsed, "counts": counts}), flush=True)
    finally:
        teacher.close()
    manifest = {
        "positions": len(selected),
        "start": a.start,
        "nodes_per_position": a.nodes,
        "split_counts": counts,
        "elapsed_s": time.monotonic() - started,
    }
    a.output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
