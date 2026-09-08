#!/usr/bin/env python3
"""Export the root-policy TorchScript parameters into a tiny NumPy runtime artifact."""
from pathlib import Path
import argparse
import numpy as np
import torch


def main() -> int:
    ap=argparse.ArgumentParser();ap.add_argument('model',type=Path);ap.add_argument('output',type=Path);a=ap.parse_args()
    m=torch.jit.load(str(a.model),map_location='cpu')
    params={name:p.detach().cpu().numpy().astype(np.float32) for name,p in m.named_parameters()}
    expected={'board.0.weight','board.0.bias','move.0.weight','move.0.bias','head.0.weight','head.0.bias','head.2.weight','head.2.bias'}
    if set(params)!=expected: raise SystemExit(f'unexpected parameters: {sorted(params)}')
    a.output.parent.mkdir(parents=True,exist_ok=True)
    np.savez_compressed(a.output,
        board_w=params['board.0.weight'],board_b=params['board.0.bias'],
        move_w=params['move.0.weight'],move_b=params['move.0.bias'],
        head_w=params['head.0.weight'],head_b=params['head.0.bias'],
        out_w=params['head.2.weight'],out_b=params['head.2.bias'])
    print(a.output, a.output.stat().st_size)
    return 0
if __name__=='__main__': raise SystemExit(main())
