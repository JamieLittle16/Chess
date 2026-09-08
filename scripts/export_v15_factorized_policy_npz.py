#!/usr/bin/env python3
from pathlib import Path
import sys,numpy as np,torch
if len(sys.argv)!=3:raise SystemExit('usage: export_v15_factorized_policy_npz.py MODEL.pt OUT.npz')
m=torch.jit.load(sys.argv[1],map_location='cpu');sd=m.state_dict()
arr={
 'board_w':sd['b.weight'].cpu().numpy().astype(np.float32),
 'board_b':sd['b.bias'].cpu().numpy().astype(np.float32),
 'move_w':sd['m.weight'].cpu().numpy().astype(np.float32),
 'move_b':sd['m.bias'].cpu().numpy().astype(np.float32),
 'interact':sd['interact'].cpu().numpy().astype(np.float32),
 'move_out':sd['move_out'].cpu().numpy().astype(np.float32),
 'bias':np.asarray([float(sd['bias'])],dtype=np.float32),
}
Path(sys.argv[2]).parent.mkdir(parents=True,exist_ok=True);np.savez_compressed(sys.argv[2],**arr);print(sys.argv[2]);[print(k,v.shape) for k,v in arr.items()]
