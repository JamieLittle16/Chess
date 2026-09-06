#!/usr/bin/env python3
"""Mark the legacy normal-qsearch wrapper test-only after mode-aware NMP plumbing."""
from pathlib import Path

path = Path("crates/chess-search/src/quiescence.rs")
text = path.read_text()
old = "    #[allow(clippy::too_many_arguments)]\n    pub(super) fn quiescence<C: SearchControl>("
new = "    #[cfg(test)]\n    #[allow(clippy::too_many_arguments)]\n    pub(super) fn quiescence<C: SearchControl>("
if text.count(old) != 1:
    raise SystemExit(f"qsearch wrapper: expected one match, found {text.count(old)}")
path.write_text(text.replace(old, new, 1))
