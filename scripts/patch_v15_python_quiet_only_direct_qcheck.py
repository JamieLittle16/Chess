#!/usr/bin/env python3
"""Apply lean direct-slider qsearch checks only when V14 has no tactical move."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    direct = Path(__file__).with_name("patch_v15_python_direct_slider_qcheck.py")
    subprocess.run([sys.executable, str(direct), str(args.path)], check=True)

    source = args.path.read_text()
    old = "        if qply == 0:\n            enemy_king = int(\n"
    new = "        if qply == 0 and count == 0:\n            enemy_king = int(\n"
    if source.count(old) != 1:
        raise SystemExit(f"quiet-only gate: expected one direct-qcheck anchor, found {source.count(old)}")
    args.path.write_text(source.replace(old, new, 1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
