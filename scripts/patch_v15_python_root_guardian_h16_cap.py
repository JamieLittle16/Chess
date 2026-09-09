#!/usr/bin/env python3
"""Convert the injected root H32 guardian to H16 and hard-cap its root correction.

Apply after patch_v15_python_root_h32_guardian.py, using the H16 topology artifact renamed as
guardian_h32.npz.  H16 retains nearly all measured Gestalt-teacher fidelity at half the hidden lanes.
The final root-side correction is capped so the learned static advisor can break close search ties but
cannot overrule a multi-ply tactical score by hundreds of centipawns.
"""
from __future__ import annotations
import argparse
from pathlib import Path


def one(s: str, old: str, new: str, label: str) -> str:
    n=s.count(old)
    if n!=1: raise SystemExit(f'{label}: expected 1, found {n}')
    return s.replace(old,new,1)


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('path',type=Path)
    ap.add_argument('--cap-cp',type=int,required=True)
    a=ap.parse_args()
    if not 1 <= a.cap_cp <= 200: raise SystemExit('cap-cp must be 1..200')
    s=a.path.read_text()
    s=one(s,'GUARDIAN_FEATURE_WEIGHTS.shape != (6912, 32)','GUARDIAN_FEATURE_WEIGHTS.shape != (6912, 16)','feature shape')
    s=one(s,'GUARDIAN_FEATURE_BIAS.shape != (32,) or GUARDIAN_OUTPUT_US.shape != (32,) or GUARDIAN_OUTPUT_THEM.shape != (32,)','GUARDIAN_FEATURE_BIAS.shape != (16,) or GUARDIAN_OUTPUT_US.shape != (16,) or GUARDIAN_OUTPUT_THEM.shape != (16,)','head shape')
    s=one(s,'GUARDIAN_HIDDEN = 32','GUARDIAN_HIDDEN = 16','hidden width')
    old='''    # Convert child POV to the mover/root POV before blending.\n    return -trunc_div_scalar(delta_child * GUARDIAN_BLEND_NUM, GUARDIAN_BLEND_DEN)\n'''
    new=f'''    # Convert child POV to the mover/root POV before blending, then hard-cap the static\n    # advisor so it can resolve close root choices without overruling proven search by large margins.\n    correction = -trunc_div_scalar(delta_child * GUARDIAN_BLEND_NUM, GUARDIAN_BLEND_DEN)\n    if correction > {a.cap_cp}:\n        correction = {a.cap_cp}\n    elif correction < -{a.cap_cp}:\n        correction = -{a.cap_cp}\n    return correction\n'''
    s=one(s,old,new,'final correction')
    a.path.write_text(s)
    return 0

if __name__=='__main__': raise SystemExit(main())
