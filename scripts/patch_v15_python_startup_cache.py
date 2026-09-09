#!/usr/bin/env python3
"""Patch the final Python V15 package for portable precompiled Numba startup.

The competition worker has a hard startup window.  The production package used to compile the
entire recursive Numba search graph during ``import agent``.  This patch keeps the search/evaluation
semantics but makes the externally-entered dispatchers cacheable, replaces the dynamic ctypes
``clock()`` pointer with a cache-safe LLVM symbol binding, and forces a portable x86-64 cache target
before Numba is imported.
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
    search = replace_once(
        search,
        "import ctypes\nfrom pathlib import Path\n\nimport numpy as np\nfrom numba import njit\n",
        "from pathlib import Path\n\nimport numpy as np\nfrom llvmlite import ir\nfrom numba import extending, njit, types\nfrom numba.core.cgutils import get_or_insert_function\n",
        label="cache-safe clock imports",
    )
    search = replace_once(
        search,
        "# Linux competition image: libc clock() gives process CPU ticks. Numba can call ctypes functions\n"
        "# directly in nopython mode, giving search a true hard deadline instead of relying on a calibrated\n"
        "# node-count proxy. On glibc CLOCKS_PER_SEC is 1_000_000. We sample only every 128 nodes, so the\n"
        "# deadline probe costs well below one percent of search time.\n"
        "_CPU_CLOCK = ctypes.CDLL(None).clock\n"
        "_CPU_CLOCK.argtypes = []\n"
        "_CPU_CLOCK.restype = ctypes.c_long\n"
        "_CPU_TICKS_PER_MS = 1_000\n",
        "# Linux competition image: libc clock() gives process CPU ticks. Bind the external libc symbol\n"
        "# directly in LLVM instead of storing a ctypes function pointer.  The latter is a dynamic global\n"
        "# and prevents Numba's on-disk cache from serialising the production search.  The external symbol\n"
        "# remains the same glibc clock() call and therefore preserves the real process-CPU deadline.\n"
        "@extending.intrinsic\n"
        "def _cpu_clock_ticks(typingctx):\n"
        "    def codegen(context, builder, signature, args):\n"
        "        function_type = ir.FunctionType(ir.IntType(64), ())\n"
        "        function = get_or_insert_function(builder.module, function_type, \"clock\")\n"
        "        return builder.call(function, ())\n"
        "\n"
        "    return types.int64(), codegen\n"
        "\n"
        "\n"
        "_CPU_TICKS_PER_MS = 1_000\n",
        label="cache-safe libc clock",
    )
    clock_uses = search.count("_CPU_CLOCK()")
    if clock_uses != 5:
        raise SystemExit(f"clock call sites: expected 5, found {clock_uses}")
    search = search.replace("_CPU_CLOCK()", "_cpu_clock_ticks()")

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
