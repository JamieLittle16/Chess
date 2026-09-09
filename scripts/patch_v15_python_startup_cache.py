#!/usr/bin/env python3
"""Patch the final Python V15 package for portable precompiled Numba startup.

The competition worker has a hard startup window.  The production package used to compile the
entire recursive Numba search graph during ``import agent``.  This patch keeps exactly the same
search/evaluation semantics but makes the externally-entered dispatchers cacheable and forces a
portable x86-64 cache target before Numba is imported.
"""
from __future__ import annotations

import sys
from pathlib import Path


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: patch_v15_python_startup_cache.py AGENT.py NUMBA_SEARCH.py")

    agent_path = Path(sys.argv[1])
    search_path = Path(sys.argv[2])

    agent = agent_path.read_text()
    agent = replace_once(
        agent,
        "import time\nfrom dataclasses import dataclass\nfrom pathlib import Path\nfrom typing import Final\n\nimport chess\nimport numpy as np\n",
        "import os\nimport time\nfrom dataclasses import dataclass\nfrom pathlib import Path\nfrom typing import Final\n\n# The competition has a hard process-start window.  Load the production search from the\n# precompiled in-tree Numba cache shipped in the submission instead of recompiling LLVM at import.\n# ``generic`` makes the cache portable across Linux x86-64 hosts; the filesystem-agnostic locator\n# preserves cache validity after ZIP extraction rounds source mtimes to whole seconds.\nos.environ.setdefault(\"NUMBA_CPU_NAME\", \"generic\")\nos.environ.setdefault(\n    \"NUMBA_CACHE_LOCATOR_CLASSES\",\n    \"numba.core.caching.InTreeCacheLocatorFsAgnostic\",\n)\n\nimport chess\nimport numpy as np\n",
        label="agent cache environment",
    )
    agent_path.write_text(agent)

    search = search_path.read_text()
    for function_name in (
        "evaluate",
        "position_key",
        "iterative_search_stateful_timed_cached",
    ):
        old = f"@njit(cache=False)\ndef {function_name}("
        new = f"@njit(cache=True)\ndef {function_name}("
        search = replace_once(search, old, new, label=f"cache {function_name}")
    search_path.write_text(search)


if __name__ == "__main__":
    main()
