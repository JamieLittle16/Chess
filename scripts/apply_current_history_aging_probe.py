#!/usr/bin/env python3
"""Isolate game-local History-v2 persistence on the current production search stack."""

from __future__ import annotations

from pathlib import Path


def replace_count(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != expected:
        raise RuntimeError(
            f"{path}: expected {expected} occurrences of {old!r}, found {actual}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    history = Path("crates/chess-search/src/history.rs")
    replace_count(
        history,
        """    pub(super) fn clear(&mut self) {\n        self.main.fill(0);\n        self.continuation.fill(0);\n    }\n\n    #[must_use]\n    pub(super) fn score(""",
        """    #[allow(dead_code)]\n    pub(super) fn clear(&mut self) {\n        self.main.fill(0);\n        self.continuation.fill(0);\n    }\n\n    /// Retain useful same-game evidence while decaying stale move preferences.\n    pub(super) fn age(&mut self) {\n        for entry in &mut self.main {\n            *entry = (i32::from(*entry) * 3 / 4) as i16;\n        }\n        for entry in &mut self.continuation {\n            *entry = (i32::from(*entry) * 3 / 4) as i16;\n        }\n    }\n\n    #[must_use]\n    pub(super) fn score(""",
        1,
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

    print("applied isolated current-main game-local history aging")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
