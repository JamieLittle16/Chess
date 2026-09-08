#!/usr/bin/env python3
"""Export the trained TorchScript root policy into a NumPy-only runtime weight file."""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("model", type=Path)
    ap.add_argument("output", type=Path)
    args = ap.parse_args()

    model = torch.jit.load(str(args.model), map_location="cpu")
    state = {name: value.detach().cpu().numpy() for name, value in model.named_parameters()}
    required = {
        "board.0.weight",
        "board.0.bias",
        "move.0.weight",
        "move.0.bias",
        "head.0.weight",
        "head.0.bias",
        "head.2.weight",
        "head.2.bias",
    }
    missing = required - set(state)
    if missing:
        raise SystemExit(f"missing policy parameters: {sorted(missing)}; got={sorted(state)}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        args.output,
        board_w=np.asarray(state["board.0.weight"], dtype=np.float32),
        board_b=np.asarray(state["board.0.bias"], dtype=np.float32),
        move_w=np.asarray(state["move.0.weight"], dtype=np.float32),
        move_b=np.asarray(state["move.0.bias"], dtype=np.float32),
        head_w=np.asarray(state["head.0.weight"], dtype=np.float32),
        head_b=np.asarray(state["head.0.bias"], dtype=np.float32),
        out_w=np.asarray(state["head.2.weight"], dtype=np.float32).reshape(-1),
        out_b=np.asarray(state["head.2.bias"], dtype=np.float32).reshape(-1),
    )
    print(args.output)
    for key in ("board_w", "board_b", "move_w", "move_b", "head_w", "head_b", "out_w", "out_b"):
        with np.load(args.output, allow_pickle=False) as data:
            print(key, data[key].shape)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
