#!/usr/bin/env python3
"""Make a competition package load precompiled portable Numba code instead of rebuilding LLVM IR."""
from pathlib import Path
import sys

root = Path(sys.argv[1])
agent = root / "agent.py"
s = agent.read_text()
anchor = "import time\n"
insert = '''import os\nimport time\n\n# Release packages carry a Numba cache compiled for LLVM's generic x86-64 CPU.  Set the same\n# target before importing any Numba-backed module so cache lookup is portable across competition\n# hosts instead of keying native code to the build runner's exact CPU.\nos.environ.setdefault("NUMBA_CPU_NAME", "generic")\n'''
if s.count(anchor) != 1:
    raise SystemExit(f"agent import anchor count={s.count(anchor)}")
s = s.replace(anchor, insert, 1)
agent.write_text(s)

changed = 0
for name in ("numba_core.py", "numba_search.py", "v14_student_single_runtime.py"):
    p = root / "experiments" / name
    text = p.read_text()
    n = text.count("cache=False")
    if n == 0:
        raise SystemExit(f"no cache=False decorators found in {name}")
    text = text.replace("cache=False", "cache=True")
    p.write_text(text)
    changed += n
print(f"CACHE_DECORATORS_ENABLED {changed}")
