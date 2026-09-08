#!/usr/bin/env python3
"""Assemble lean Search-v2 parity: history/LMR + one-pass ordering, retaining V14 TT identity."""
from pathlib import Path
import subprocess
import sys
import tempfile

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_python_rust_parity_stack2.py SEARCH.py")
repo = Path(__file__).resolve().parents[1]
source = (repo / "scripts/patch_v15_python_rust_parity_stack1.py").read_text()
old = '''subprocess.run(\n    [sys.executable, str(repo / "scripts/patch_v15_python_rust_tt_parity.py"), str(search)],\n    check=True,\n)\n'''
if source.count(old) != 1:
    raise SystemExit("TT patch call anchor changed")
source = source.replace(old, "", 1)
old = '''if 'TT_CONTEXTS_OFFSET' in s:\n    raise SystemExit('history-sensitive TT storage survived stack assembly')\n'''
if source.count(old) != 1:
    raise SystemExit("TT assertion anchor changed")
source = source.replace(old, "", 1)
with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
    f.write(source)
    temp = f.name
try:
    subprocess.run([sys.executable, temp, sys.argv[1]], cwd=repo, check=True)
finally:
    Path(temp).unlink(missing_ok=True)
