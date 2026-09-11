#!/usr/bin/env python3
"""After SEE ordering patch, run swap-off only when victim is strictly cheaper than attacker."""
from __future__ import annotations
import argparse
from pathlib import Path

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('path',type=Path); args=ap.parse_args()
    s=args.path.read_text()
    old='if int(PIECE_VALUE[target]) <= int(PIECE_VALUE[attacker]):'
    new='if int(PIECE_VALUE[target]) < int(PIECE_VALUE[attacker]):'
    if s.count(old)!=2:
        raise RuntimeError(f'expected 2 SEE gates, found {s.count(old)}')
    args.path.write_text(s.replace(old,new))
    return 0

if __name__=='__main__': raise SystemExit(main())
