#!/usr/bin/env python3
"""Train the H64 root-policy pilot with exactly the cheap runtime move features.

The original pilot includes a python-chess `gives_check` bit. Computing that bit for every root
candidate inside the submission would require an extra make/check/unmake pass. For deployment we
zero that feature during both training and evaluation; all remaining features are available directly
from the encoded board/move representation before search.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_v15_root_policy as base

_original_move_features = base.move_features


def runtime_move_features(board, move):
    x = _original_move_features(board, move)
    # Layout tail is capture, gives_check, castling, en-passant.
    x[-3] = 0.0
    return x


base.move_features = runtime_move_features

if __name__ == "__main__":
    raise SystemExit(base.main())
