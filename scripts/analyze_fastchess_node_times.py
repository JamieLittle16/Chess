#!/usr/bin/env python3
"""Summarize per-engine fixed-node search time from a Fastchess PGN without extra dependencies."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

TAG = re.compile(r'^\[([A-Za-z0-9_]+) "([^"]*)"\]$', re.MULTILINE)
COMMENT = re.compile(r"\{[^{}]*?\s([0-9]+(?:\.[0-9]+)?)s,\s*n=([0-9]+),\s*nps=([0-9]+)\}")


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take percentile of empty data")
    index = min(len(ordered) - 1, int(fraction * len(ordered)))
    return ordered[index]


def summarize(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    samples: dict[str, list[tuple[float, int]]] = {}

    for game in re.split(r"(?=^\[Event )", text, flags=re.MULTILINE):
        if not game.strip():
            continue
        tags = dict(TAG.findall(game))
        white = tags.get("White")
        black = tags.get("Black")
        if white is None or black is None:
            continue
        fen = tags.get("FEN", "")
        fields = fen.split()
        side = fields[1] if len(fields) >= 2 and fields[1] in {"w", "b"} else "w"
        body = game.split("\n\n", 1)[1] if "\n\n" in game else ""

        for match in COMMENT.finditer(body):
            engine = white if side == "w" else black
            seconds = float(match.group(1))
            nodes = int(match.group(2))
            samples.setdefault(engine, []).append((seconds, nodes))
            side = "b" if side == "w" else "w"

    engines: dict[str, object] = {}
    for engine, rows in sorted(samples.items()):
        times = [seconds for seconds, _ in rows]
        total_seconds = sum(times)
        total_nodes = sum(nodes for _, nodes in rows)
        engines[engine] = {
            "moves": len(rows),
            "mean_seconds": statistics.fmean(times),
            "median_seconds": statistics.median(times),
            "p90_seconds": percentile(times, 0.90),
            "total_seconds": total_seconds,
            "total_nodes": total_nodes,
            "effective_nps": total_nodes / total_seconds if total_seconds else None,
        }

    if not engines:
        raise ValueError(f"no fixed-node Fastchess comments found in {path}")
    return {"pgn": str(path), "engines": engines}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pgn", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    report = summarize(args.pgn)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
