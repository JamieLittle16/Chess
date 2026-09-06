#!/usr/bin/env python3
"""Select a deterministic disjoint EPD sample from a pinned ZIP source.

The ranking rule intentionally matches the repository's original UHO suite:
SHA256(UTF8(seed) + NUL + normalized EPD line bytes), with the lowest hashes selected.
Source line numbers listed in an existing suite manifest can be excluded to create a true holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import zipfile
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-zip", type=Path, required=True)
    parser.add_argument("--member", required=True)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--exclude-manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    return parser.parse_args()


def excluded_lines(path: Path | None) -> set[int]:
    if path is None:
        return set()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    return set(manifest["selection"]["selected_source_lines"])


def main() -> None:
    args = parse_args()
    if args.count <= 0:
        raise SystemExit("--count must be positive")

    excluded = excluded_lines(args.exclude_manifest)
    seed_prefix = args.seed.encode("utf-8") + b"\0"
    # Max-heap via negated 256-bit ranks. Entries are (-rank, line_no, line_bytes, digest_hex).
    chosen: list[tuple[int, int, bytes, str]] = []
    source_lines = 0

    with zipfile.ZipFile(args.source_zip) as archive:
        with archive.open(args.member) as source:
            for line_no, raw in enumerate(source, start=1):
                source_lines = line_no
                if line_no in excluded:
                    continue
                line = raw.rstrip(b"\r\n")
                if not line:
                    continue
                digest = hashlib.sha256(seed_prefix + line).digest()
                rank = int.from_bytes(digest, "big")
                item = (-rank, line_no, line, digest.hex())
                if len(chosen) < args.count:
                    heapq.heappush(chosen, item)
                elif rank < -chosen[0][0]:
                    heapq.heapreplace(chosen, item)

    if len(chosen) != args.count:
        raise SystemExit(f"only selected {len(chosen)} positions from {source_lines} source lines")

    selected = sorted(chosen, key=lambda item: -item[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("wb") as output:
        for _, _, line, _ in selected:
            output.write(line + b"\n")

    output_sha = hashlib.sha256(args.output.read_bytes()).hexdigest()
    metadata = {
        "schema_version": 1,
        "format": "epd",
        "positions": args.count,
        "suite_id": "m4-e4-uho-holdout-100-v1",
        "sha256": output_sha,
        "selection": {
            "algorithm": "lowest-sha256-rank-v1",
            "ordering": "ascending rank_sha256",
            "rank_input": "utf8(seed) + NUL + normalized EPD line bytes",
            "seed": args.seed,
            "excluded_source_lines": sorted(excluded),
            "selected_source_lines": [line_no for _, line_no, _, _ in selected],
            "selected_rank_sha256": [digest for _, _, _, digest in selected],
        },
        "source": {
            "archive": args.source_zip.name,
            "member": args.member,
            "lines_scanned": source_lines,
        },
    }
    args.metadata.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(output_sha)


if __name__ == "__main__":
    main()
