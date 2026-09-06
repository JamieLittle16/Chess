#!/usr/bin/env python3
"""Derive the frozen M3 opening suite from a pinned Stockfish CC0 book.

The source archive is intentionally external and pinned by commit/blob/SRI. This script verifies the
uncompressed book exactly as the upstream repository does, then selects the 100 smallest stable
SHA-256 ranks. Selection therefore spans the full source corpus without relying on its first lines or
on a runtime RNG.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import heapq
import json
import sys
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

SOURCE_REPOSITORY = "official-stockfish/books"
SOURCE_COMMIT = "65815ccdbc7727cd4f6aee252ba8f67fb740e92f"
SOURCE_ARCHIVE = "UHO_Lichess_4852_v1.epd.zip"
SOURCE_MEMBER = "UHO_Lichess_4852_v1.epd"
SOURCE_GIT_BLOB_SHA = "e439636101786177ece850d3607356891c1cc2cd"
SOURCE_ARCHIVE_SIZE = 42_877_788
SOURCE_TOTAL_POSITIONS = 2_632_036
SOURCE_SRI_SHA384_BASE64 = "QHAU1P3LurcJr7UTRI7HZCVFsoYBWC3OTsBqZY/FfQA6VQo3MmECWtByB4gVACW5"
SOURCE_LICENSE = "CC0-1.0"
SUITE_ID = "m3-uho-lichess-100-v1"
SELECTION_SEED = "Chess/m3-uho-lichess-100-v1"
SELECTION_COUNT = 100


class DerivationError(ValueError):
    """Raised when the pinned source or derived suite violates its contract."""


@dataclass(frozen=True)
class SelectedPosition:
    rank_sha256: str
    source_line: int
    epd: str


def normalized_lines(source) -> tuple[list[SelectedPosition], str, int]:
    """Stream upstream content, verify SHA-384 input bytes and retain the 100 lowest ranks."""
    sri = hashlib.sha384()
    heap: list[tuple[int, int, bytes, bytes]] = []
    count = 0
    seed = SELECTION_SEED.encode("ascii") + b"\0"

    for source_line, raw in enumerate(source, start=1):
        normalized = raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
        sri.update(normalized)
        line = normalized.rstrip(b"\n")
        if not line:
            continue
        count += 1
        digest = hashlib.sha256(seed + line).digest()
        score = int.from_bytes(digest, "big")
        entry = (-score, source_line, digest, line)
        if len(heap) < SELECTION_COUNT:
            heapq.heappush(heap, entry)
        elif -score > heap[0][0]:
            heapq.heapreplace(heap, entry)

    encoded_sri = base64.b64encode(sri.digest()).decode("ascii")
    selected = [
        SelectedPosition(
            rank_sha256=digest.hex(),
            source_line=source_line,
            epd=line.decode("utf-8"),
        )
        for _, source_line, digest, line in heap
    ]
    selected.sort(key=lambda item: (item.rank_sha256, item.epd))
    return selected, encoded_sri, count


def derive(archive: Path, output_dir: Path) -> tuple[Path, Path]:
    archive = archive.expanduser().resolve(strict=True)
    if not archive.is_file():
        raise DerivationError(f"source archive is not a regular file: {archive}")
    if archive.stat().st_size != SOURCE_ARCHIVE_SIZE:
        raise DerivationError(
            f"source archive size mismatch: expected {SOURCE_ARCHIVE_SIZE}, got {archive.stat().st_size}"
        )

    archive_sha256 = hashlib.sha256(archive.read_bytes()).hexdigest()
    try:
        with zipfile.ZipFile(archive) as zipped:
            names = zipped.namelist()
            if names != [SOURCE_MEMBER]:
                raise DerivationError(
                    f"source archive members mismatch: expected [{SOURCE_MEMBER!r}], got {names!r}"
                )
            with zipped.open(SOURCE_MEMBER) as source:
                selected, sri, total = normalized_lines(source)
    except zipfile.BadZipFile as exc:
        raise DerivationError(f"invalid source ZIP: {exc}") from exc

    if sri != SOURCE_SRI_SHA384_BASE64:
        raise DerivationError(f"source SRI mismatch: expected {SOURCE_SRI_SHA384_BASE64}, got {sri}")
    if total != SOURCE_TOTAL_POSITIONS:
        raise DerivationError(
            f"source position count mismatch: expected {SOURCE_TOTAL_POSITIONS}, got {total}"
        )
    if len(selected) != SELECTION_COUNT:
        raise DerivationError(f"expected {SELECTION_COUNT} selected positions, got {len(selected)}")
    if len({item.epd for item in selected}) != SELECTION_COUNT:
        raise DerivationError("derived suite contains duplicate EPD positions")

    output_dir.mkdir(parents=True, exist_ok=True)
    epd_path = output_dir / f"{SUITE_ID}.epd"
    metadata_path = output_dir / f"{SUITE_ID}.json"
    epd_bytes = ("\n".join(item.epd for item in selected) + "\n").encode("utf-8")
    epd_path.write_bytes(epd_bytes)

    metadata = {
        "schema_version": 1,
        "suite_id": SUITE_ID,
        "format": "epd",
        "positions": SELECTION_COUNT,
        "sha256": hashlib.sha256(epd_bytes).hexdigest(),
        "selection": {
            "algorithm": "lowest-sha256-rank-v1",
            "seed": SELECTION_SEED,
            "rank_input": "utf8(seed) + NUL + normalized EPD line bytes",
            "ordering": "ascending rank_sha256",
        },
        "source": {
            "repository": SOURCE_REPOSITORY,
            "commit": SOURCE_COMMIT,
            "archive": SOURCE_ARCHIVE,
            "member": SOURCE_MEMBER,
            "git_blob_sha": SOURCE_GIT_BLOB_SHA,
            "archive_size_bytes": SOURCE_ARCHIVE_SIZE,
            "archive_sha256": archive_sha256,
            "positions": SOURCE_TOTAL_POSITIONS,
            "sri_sha384_base64": SOURCE_SRI_SHA384_BASE64,
            "license": SOURCE_LICENSE,
        },
        "selected": [asdict(item) for item in selected],
    }
    metadata_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return epd_path, metadata_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        epd_path, metadata_path = derive(args.archive, args.output_dir)
    except (OSError, UnicodeDecodeError, DerivationError) as exc:
        print(f"opening-suite derivation: {exc}", file=sys.stderr)
        return 2
    print(epd_path)
    print(metadata_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
