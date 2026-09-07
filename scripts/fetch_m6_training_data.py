#!/usr/bin/env python3
"""Fetch or verify an immutable M6 training corpus from a JSON manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def load_manifest(path: Path) -> dict[str, Any]:
    manifest = json.loads(path.read_text())
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported manifest schema")
    for key in ("id", "purpose", "source", "content", "license", "training"):
        if key not in manifest:
            raise ValueError(f"manifest missing {key!r}")

    source = manifest["source"]
    content = manifest["content"]
    for key in ("provider", "repo_id", "repo_type", "revision", "filename"):
        if not source.get(key):
            raise ValueError(f"source missing {key!r}")
    if source["provider"] != "huggingface":
        raise ValueError("only huggingface sources are supported in v1")
    if source["repo_type"] != "dataset":
        raise ValueError("M6 v1 expects a Hugging Face dataset repository")

    expected_size = content.get("bytes")
    expected_sha = content.get("sha256")
    if not isinstance(expected_size, int) or expected_size <= 0:
        raise ValueError("content.bytes must be a positive integer")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError("content.sha256 must be a 64-character digest")
    int(expected_sha, 16)
    return manifest


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected_size = int(manifest["content"]["bytes"])
    expected_sha = str(manifest["content"]["sha256"])
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"size mismatch for {path}: expected {expected_size}, got {actual_size}"
        )
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise ValueError(
            f"SHA-256 mismatch for {path}: expected {expected_sha}, got {actual_sha}"
        )
    return {"bytes": actual_size, "sha256": actual_sha}


def fetch(manifest: dict[str, Any], destination: Path) -> Path:
    try:
        from huggingface_hub import hf_hub_download
    except ImportError as error:
        raise RuntimeError(
            "fetching requires huggingface_hub; install with `python -m pip install huggingface_hub`"
        ) from error

    source = manifest["source"]
    downloaded = Path(
        hf_hub_download(
            repo_id=source["repo_id"],
            repo_type=source["repo_type"],
            revision=source["revision"],
            filename=source["filename"],
        )
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    if downloaded.resolve() != destination.resolve():
        shutil.copyfile(downloaded, destination)
    return destination


def write_lock(
    lock_path: Path,
    manifest_path: Path,
    manifest: dict[str, Any],
    verified: dict[str, Any],
    data_path: Path,
) -> None:
    manifest_bytes = manifest_path.read_bytes()
    lock = {
        "schema_version": 1,
        "manifest_id": manifest["id"],
        "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
        "data_path": str(data_path.resolve()),
        "data_bytes": verified["bytes"],
        "data_sha256": verified["sha256"],
        "source": manifest["source"],
        "license": manifest["license"],
        "purpose": manifest["purpose"],
    }
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify-only", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument(
        "--acknowledge-license",
        help="must equal the manifest license identifier before a network fetch",
    )
    parser.add_argument("--print-manifest", action="store_true")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    if args.print_manifest:
        print(json.dumps(manifest, indent=2, sort_keys=True))
        if args.output is None and args.verify_only is None:
            return 0

    if args.verify_only is not None and args.output is not None:
        parser.error("--verify-only and --output are mutually exclusive")
    if args.verify_only is None and args.output is None:
        parser.error("provide --output to fetch or --verify-only to validate an existing file")

    if args.verify_only is not None:
        data_path = args.verify_only
    else:
        license_id = str(manifest["license"]["identifier"])
        if args.acknowledge_license != license_id:
            raise ValueError(
                f"refusing network fetch without `--acknowledge-license {license_id}`"
            )
        data_path = fetch(manifest, args.output)

    if not data_path.is_file():
        raise FileNotFoundError(data_path)
    verified = verify_file(data_path, manifest)
    print(
        f"verified {manifest['id']}: {verified['bytes']} bytes sha256={verified['sha256']}"
    )

    if args.lock is not None:
        write_lock(args.lock, args.manifest, manifest, verified, data_path)
        print(f"wrote provenance lock: {args.lock}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
