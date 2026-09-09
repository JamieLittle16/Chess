#!/usr/bin/env python3
"""Fuse exact V14 absolute768 accumulator updates into one lane pass."""
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
start=s.index('@njit(cache=False)\ndef advance_absolute768_accumulator_into(')
end=s.index('\n\n@njit(cache=False, inline="always")\ndef trunc_div_scalar',start)
new='''@njit(cache=False)\ndef advance_absolute768_accumulator_into(\n    board: np.ndarray, side: int, move: int, parent: np.ndarray, child: np.ndarray, feature_weights: np.ndarray,\n) -> None:\n    hidden=parent.shape[0]; frm=move_from(move); to=move_to(move); promotion=move_promotion(move)\n    moving=int(board[frm]); placed=side*promotion if promotion else moving\n    ff=absolute768_feature_index(moving,frm); tf=absolute768_feature_index(placed,to)\n    cap_sq=to; captured=int(board[to])\n    if move & FLAG_EP:\n        cap_sq=to-8*side; captured=int(board[cap_sq])\n    if captured==EMPTY and not (move & FLAG_CASTLE):\n        for n in range(hidden): child[n]=int(parent[n])-int(feature_weights[ff,n])+int(feature_weights[tf,n])\n        return\n    if captured!=EMPTY:\n        cf=absolute768_feature_index(captured,cap_sq)\n        for n in range(hidden): child[n]=int(parent[n])-int(feature_weights[ff,n])-int(feature_weights[cf,n])+int(feature_weights[tf,n])\n        return\n    if to==6: rf,rt=7,5\n    elif to==2: rf,rt=0,3\n    elif to==62: rf,rt=63,61\n    else: rf,rt=56,59\n    rook=side*ROOK; rff=absolute768_feature_index(rook,rf); rtf=absolute768_feature_index(rook,rt)\n    for n in range(hidden):\n        v=int(parent[n]); v-=int(feature_weights[ff,n]); v+=int(feature_weights[tf,n]); v-=int(feature_weights[rff,n]); v+=int(feature_weights[rtf,n]); child[n]=v\n'''
p.write_text(s[:start]+new+s[end:])
