#!/usr/bin/env python3
"""Train the existing V14 H64 deployment shape to imitate Rust Gestalt over the exact V13 prefix.

This wrapper deliberately reuses the proven V14 trainer/quantiser. The only semantic change is that
baseline evaluation is read from exact packaged V14's `_evaluate_state_v13_only`, so the resulting
H64 model can replace `v14_student_h64.npz` without adding another accumulator or inference pass.
"""
from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_v14_single_residual as base


def load_exact_v14_v13_api(engine_dir: Path):
    sys.path.insert(0, str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH, _build_eval_state_into, _evaluate_state_v13_only
    return encode_position, _build_eval_state_into, _evaluate_state_v13_only, int(EVAL_WIDTH)

base.load_v13_api = load_exact_v14_v13_api

if __name__ == "__main__":
    raise SystemExit(base.main())
