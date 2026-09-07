#!/usr/bin/env python3
"""Wire the objective root-analysis module into chess-search once."""
from pathlib import Path

path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()
needle = "mod move_picker;\nmod quiescence;\n"
replacement = "mod move_picker;\nmod quiescence;\nmod root_analysis;\n\npub use root_analysis::RootCandidate;\n"
count = text.count(needle)
if count != 1:
    raise SystemExit(f"root-analysis module anchor: expected one match, found {count}")
path.write_text(text.replace(needle, replacement, 1))
