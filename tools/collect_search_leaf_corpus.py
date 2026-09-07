#!/usr/bin/env python3
"""Collect a bounded, leakage-safe corpus from real search evaluation calls.

The engine must be built with the `search-trace` Cargo feature. One engine process is
started per opening root so the compile-time trace sink can attach an immutable group id
to every observed static-evaluation position. The resulting TSV is globally deduplicated
by FEN: if the same position is reached from more than one root, its first deterministic
group owns it so future group-based train/validation/holdout splits cannot leak that
position across splits.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
import subprocess
import sys


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def load_roots(path: Path, limit: int) -> list[str]:
    roots = [
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    if limit <= 0:
        raise ValueError("--roots must be positive")
    if limit > len(roots):
        raise ValueError(f"requested {limit} roots but {path} contains only {len(roots)}")
    selected = roots[:limit]
    for index, fen in enumerate(selected):
        if len(fen.split()) != 6:
            raise ValueError(f"opening root {index} is not a six-field FEN: {fen!r}")
    return selected


def group_name(index: int, fen: str) -> str:
    identity = sha256_bytes(fen.encode("utf-8"))[:12]
    return f"uho-{index:04d}-{identity}"


def run_root(
    engine: Path,
    trace_file: Path,
    group: str,
    fen: str,
    nodes: int,
    stride: int,
) -> None:
    env = os.environ.copy()
    env["CHESS_SEARCH_TRACE_FILE"] = str(trace_file)
    env["CHESS_SEARCH_TRACE_GROUP"] = group
    env["CHESS_SEARCH_TRACE_STRIDE"] = str(stride)
    commands = (
        "uci\n"
        "isready\n"
        "ucinewgame\n"
        f"position fen {fen}\n"
        f"go nodes {nodes}\n"
        "quit\n"
    )
    result = subprocess.run(
        [str(engine)],
        input=commands,
        text=True,
        capture_output=True,
        env=env,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"trace engine failed for {group} with code {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    required = ("uciok", "readyok", "bestmove ")
    missing = [token for token in required if token not in result.stdout]
    if missing:
        raise RuntimeError(
            f"trace engine omitted {missing!r} for {group}\nstdout:\n{result.stdout}"
        )


def normalize_trace(
    raw_path: Path,
    output_path: Path,
    expected_groups: list[str],
) -> dict[str, object]:
    allowed = set(expected_groups)
    raw_counts: Counter[str] = Counter()
    owner_by_fen: dict[str, str] = {}
    same_group_duplicates = 0
    cross_group_duplicates = 0

    for line_number, raw_line in enumerate(raw_path.read_text().splitlines(), start=1):
        if not raw_line:
            continue
        try:
            group, fen = raw_line.split("\t", 1)
        except ValueError as error:
            raise ValueError(f"trace line {line_number} is not group<TAB>FEN") from error
        if group not in allowed:
            raise ValueError(f"trace line {line_number} has unexpected group {group!r}")
        if len(fen.split()) != 6:
            raise ValueError(f"trace line {line_number} is not a six-field FEN: {fen!r}")
        raw_counts[group] += 1
        previous = owner_by_fen.get(fen)
        if previous is None:
            owner_by_fen[fen] = group
        elif previous == group:
            same_group_duplicates += 1
        else:
            cross_group_duplicates += 1

    missing_groups = [group for group in expected_groups if raw_counts[group] == 0]
    if missing_groups:
        raise ValueError(f"trace produced no records for groups: {missing_groups}")

    rows = sorted((group, fen) for fen, group in owner_by_fen.items())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_text = "".join(f"{group}\t{fen}\n" for group, fen in rows)
    output_path.write_text(output_text)

    retained_counts: Counter[str] = Counter(group for group, _ in rows)
    return {
        "raw_record_count": sum(raw_counts.values()),
        "unique_record_count": len(rows),
        "same_group_duplicates_dropped": same_group_duplicates,
        "cross_group_duplicates_dropped": cross_group_duplicates,
        "groups": [
            {
                "group": group,
                "raw_records": raw_counts[group],
                "unique_records_retained": retained_counts[group],
            }
            for group in expected_groups
        ],
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--roots", type=int, default=16)
    parser.add_argument("--nodes", type=int, default=4_000)
    parser.add_argument("--stride", type=int, default=8)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.nodes <= 0:
        raise ValueError("--nodes must be positive")
    if args.stride <= 0:
        raise ValueError("--stride must be positive")

    engine = args.engine.resolve()
    openings = args.openings.resolve()
    if not engine.is_file():
        raise FileNotFoundError(engine)
    if not openings.is_file():
        raise FileNotFoundError(openings)

    roots = load_roots(openings, args.roots)
    groups = [group_name(index, fen) for index, fen in enumerate(roots)]
    raw_path = args.output.with_suffix(args.output.suffix + ".raw")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.unlink(missing_ok=True)
    args.output.unlink(missing_ok=True)

    for group, fen in zip(groups, roots, strict=True):
        run_root(engine, raw_path, group, fen, args.nodes, args.stride)

    stats = normalize_trace(raw_path, args.output, groups)
    manifest = {
        "schema": "chess-search-leaf-corpus-v1",
        "engine_sha256": sha256_file(engine),
        "opening_source_sha256": sha256_file(openings),
        "root_count": len(roots),
        "nodes_per_root": args.nodes,
        "trace_stride": args.stride,
        **stats,
        "corpus_sha256": sha256_file(args.output),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print(json.dumps(manifest, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
        print(f"search-leaf corpus collection failed: {error}", file=sys.stderr)
        raise SystemExit(1) from error
