#!/usr/bin/env python3
"""Activate History-v2 while retaining and aging game-local history across engine searches."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def replace_count(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != expected:
        raise RuntimeError(f"{path}: expected {expected} occurrences of {old!r}, found {actual}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    subprocess.run(
        [sys.executable, "scripts/apply_history_v2_probe.py", "--variant", "history"],
        check=True,
    )
    replace_count(
        Path("crates/chess-search/src/lib.rs"),
        "self.history.clear();",
        "self.history.age();",
        2,
    )
    replace_count(
        Path("crates/chess-search/src/root_analysis.rs"),
        "self.history.clear();",
        "self.history.age();",
        1,
    )
    print("applied M6 History-v2 aged game-local candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
