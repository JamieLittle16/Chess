#!/usr/bin/env python3
"""Apply a modestly more assertive default clock horizon over accepted LMR v3."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


engine_path = Path("crates/chess-engine/src/lib.rs")
text = engine_path.read_text()
text = replace_once(
    text,
    "/// across `moves_to_go` (or 30 moves by default), and 75% of one increment is added. The final",
    "/// across `moves_to_go` (or 24 moves by default), and 75% of one increment is added. The final",
    "clock policy documentation",
)
text = replace_once(
    text,
    "let expected_moves = u128::from(self.moves_to_go.unwrap_or(30).clamp(1, 60));",
    "let expected_moves = u128::from(self.moves_to_go.unwrap_or(24).clamp(1, 60));",
    "default clock horizon",
)
text = replace_once(
    text,
    "Duration::from_millis(1_900)",
    "Duration::from_millis(2_375)",
    "no increment expectation",
)
text = replace_once(
    text,
    "assert_eq!(increment.allocated_movetime(), Duration::from_millis(2_650));",
    "assert_eq!(increment.allocated_movetime(), Duration::from_millis(3_125));",
    "increment expectation",
)
engine_path.write_text(text)

uci_path = Path("crates/chess-uci/src/lib.rs")
text = uci_path.read_text()
text = replace_once(
    text,
    "assert_eq!(white.movetime, Some(Duration::from_millis(2_650)));",
    "assert_eq!(white.movetime, Some(Duration::from_millis(3_125)));",
    "white UCI clock expectation",
)
text = replace_once(
    text,
    "assert_eq!(black.movetime, Some(Duration::from_millis(2_450)));",
    "assert_eq!(black.movetime, Some(Duration::from_millis(2_687)));",
    "black UCI clock expectation",
)
text = replace_once(
    text,
    "assert_eq!(limits.movetime, Some(Duration::from_millis(1_900)));",
    "assert_eq!(limits.movetime, Some(Duration::from_millis(2_375)));",
    "node plus clock expectation",
)
uci_path.write_text(text)
