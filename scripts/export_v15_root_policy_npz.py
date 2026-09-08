#!/usr/bin/env python3
"""Export the tiny scripted root-policy model into plain contiguous NumPy arrays.

The competition runtime has NumPy/Numba but not PyTorch. This is an offline packaging conversion;
the resulting NPZ contains only the seven dense tensors needed by the hand-written Numba inference
path.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import numpy as np
import torch


def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('model',type=Path); ap.add_argument('output',type=Path); a=ap.parse_args()
    m=torch.jit.load(str(a.model),map_location='cpu')
    sd=m.state_dict()
    arrays={
        'board_w':sd['board.0.weight'].detach().cpu().numpy().astype(np.float32),
        'board_b':sd['board.0.bias'].detach().cpu().numpy().astype(np.float32),
        'move_w':sd['move.0.weight'].detach().cpu().numpy().astype(np.float32),
        'move_b':sd['move.0.bias'].detach().cpu().numpy().astype(np.float32),
        'head_w':sd['head.0.weight'].detach().cpu().numpy().astype(np.float32),
        'head_b':sd['head.0.bias'].detach().cpu().numpy().astype(np.float32),
        'out_w':sd['head.2.weight'].detach().cpu().numpy().reshape(-1).astype(np.float32),
        'out_b':np.asarray(sd['head.2.bias'].detach().cpu().numpy().reshape(-1)[0],dtype=np.float32),
    }
    expected={'board_w':(64,773),'board_b':(64,),'move_w':(64,149),'move_b':(64,), 'head_w':(64,128),'head_b':(64,),'out_w':(64,)}
    for k,shape in expected.items():
        if arrays[k].shape!=shape: raise SystemExit(f'{k}: expected {shape}, got {arrays[k].shape}')
    a.output.parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(a.output,**arrays)
    print(a.output, a.output.stat().st_size)
    return 0

if __name__=='__main__': raise SystemExit(main())
