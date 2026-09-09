#!/usr/bin/env python3
"""Fine-tune joint king-pair output residuals without increasing H64 inference cost.

Starts from the accepted-shape 8x8 factorized king-output model.  Only well-supported joint
king buckets are allowed to depart from the factorized parent, and each departure is ridge-shrunk
and quantized with a hard per-weight cap.  Deployment remains 64 SCReLU/output products.
"""
from __future__ import annotations

import argparse, json, hashlib, sys
from pathlib import Path
import numpy as np

INPUTS=768; HIDDEN=64; BUCKETS=8; HEADS=64; QA=255; QB=64; CP_SCALE=400; DEPLOY_DEN=12


def args():
    p=argparse.ArgumentParser()
    p.add_argument('--teacher',type=Path,required=True)
    p.add_argument('--engine-dir',type=Path,required=True)
    p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--step',type=float,default=0.12)
    p.add_argument('--ridge',type=float,required=True)
    p.add_argument('--min-support',type=int,default=50)
    p.add_argument('--max-delta-q',type=int,default=8)
    return p.parse_args()


def fen_info(fen:str):
    parts=fen.split(); board=parts[0]; stm=parts[1]
    rank=7; file=0; wk=bk=None; pieces=[]
    pmap={'P':(0,1),'N':(0,2),'B':(0,3),'R':(0,4),'Q':(0,5),'K':(0,6),
          'p':(1,1),'n':(1,2),'b':(1,3),'r':(1,4),'q':(1,5),'k':(1,6)}
    for ch in board:
        if ch=='/': rank-=1; file=0
        elif ch.isdigit(): file+=int(ch)
        else:
            sq=rank*8+file; side,kind=pmap[ch]; pieces.append((side,kind,sq))
            if ch=='K': wk=sq
            elif ch=='k': bk=sq
            file+=1
    if wk is None or bk is None: raise ValueError('missing king')
    return pieces,wk,bk,(1 if stm=='w' else -1)


def kb(sq:int, white:bool)->int:
    rank=sq>>3; file=sq&7
    if not white: rank=7-rank
    return (rank>>1)*2 + (1 if file>=4 else 0)


def feature(side:int,kind:int,sq:int)->int:
    return (0 if side==0 else 384)+(kind-1)*64+sq


def tdiv(v,div):
    v=np.asarray(v,dtype=np.int64)
    return np.where(v>=0,v//div,-((-v)//div))


def exact_hidden(x,qw0,qb0):
    a=x.astype(np.int32)@qw0.astype(np.int32)+qb0.astype(np.int32)
    c=np.clip(a,0,QA).astype(np.int64)
    h=np.square(c.astype(np.float32)/float(QA))
    return c,h


def exact_head_cp(c,pair,qw,qb):
    selected=qw[pair].astype(np.int64)
    raw=np.sum(c*c*selected,axis=1,dtype=np.int64)
    scaled=tdiv(raw,QA)+qb[pair].astype(np.int64)
    return tdiv(scaled*CP_SCALE,QA*QB).astype(np.int32)


def load_v13(engine:Path):
    sys.path.insert(0,str(engine.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH,_build_eval_state_into,_evaluate_state_v13_only
    return encode_position,_build_eval_state_into,_evaluate_state_v13_only,int(EVAL_WIDTH)


def main():
    a=args(); a.output_dir.mkdir(parents=True,exist_ok=True)
    model=a.engine_dir/'experiments/v14_student_h64.npz'
    with np.load(model) as z:
        qw0=z['feature_weights'].astype(np.int16); qb0=z['feature_bias'].astype(np.int16)
        qheads=z['output_weights'].astype(np.int16); qbias=z['output_bias'].astype(np.int32).reshape(-1)
    if qw0.shape!=(768,64) or qheads.shape!=(64,64) or qbias.shape!=(64,):
        raise SystemExit(f'expected king-output parent, got {qw0.shape} {qheads.shape} {qbias.shape}')

    rows=[]
    for line in a.teacher.read_text().splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        if r.get('teacher_mate') is None and abs(int(r['teacher_cp']))<=5000: rows.append(r)
    n=len(rows); x=np.zeros((n,INPUTS),dtype=np.float32); teacher=np.empty(n,np.float32)
    pair=np.empty(n,np.int16); sign=np.empty(n,np.float32); split=np.empty(n,np.int8)
    split_map={'train':0,'validation':1,'holdout':2}
    encode,build,v13fn,E=load_v13(a.engine_dir); v13=np.empty(n,np.float32)
    for i,r in enumerate(rows):
        pieces,wk,bk,sgn=fen_info(r['fen'])
        for side,kind,sq in pieces: x[i,feature(side,kind,sq)]=1.0
        pair[i]=kb(wk,True)*8+kb(bk,False); sign[i]=sgn; teacher[i]=int(r['teacher_cp']); split[i]=split_map[r['split']]
        # Existing Numba encoder is used only to preserve exact deployed V13 semantics.
        import chess
        b=chess.Board(r['fen']); enc=encode(b); st=np.empty(E,dtype=np.int32); build(enc.board,st); v13[i]=int(v13fn(enc.side,st))

    clipped,h=exact_hidden(x,qw0,qb0)
    parent_raw=exact_head_cp(clipped,pair,qheads,qbias).astype(np.float32)
    parent_stm=v13+sign*tdiv(parent_raw.astype(np.int64),DEPLOY_DEN).astype(np.float32)
    desired=parent_stm+a.step*np.clip(teacher-parent_stm,-1000,1000)
    y=sign*(desired-v13)*DEPLOY_DEN/CP_SCALE
    parent_pred=np.sum(h*(qheads[pair].astype(np.float32)/QB),axis=1)+qbias[pair].astype(np.float32)/(QA*QB)
    residual=y-parent_pred

    train=np.flatnonzero(split==0); val=np.flatnonzero(split==1); hold=np.flatnonzero(split==2)
    outw=qheads.copy(); outb=qbias.copy(); support=[]
    I=np.eye(HIDDEN+1,dtype=np.float64); I[-1,-1]=0.2
    for p in range(HEADS):
        ii=train[pair[train]==p]; count=len(ii)
        if count<a.min_support: continue
        Z=np.concatenate([h[ii].astype(np.float64),np.ones((count,1),np.float64)],axis=1)
        rhs=residual[ii].astype(np.float64)
        coef=np.linalg.solve(Z.T@Z+a.ridge*I,Z.T@rhs)
        dq=np.clip(np.rint(coef[:HIDDEN]*QB),-a.max_delta_q,a.max_delta_q).astype(np.int16)
        db=int(np.clip(np.rint(coef[-1]*QA*QB),-4096,4096))
        outw[p]=np.clip(outw[p].astype(np.int32)+dq.astype(np.int32),-32768,32767).astype(np.int16)
        outb[p]=np.int32(int(outb[p])+db); support.append((p,count,int(np.max(np.abs(dq))),db))

    raw=exact_head_cp(clipped,pair,outw,outb).astype(np.float32)
    deployed=v13+sign*tdiv(raw.astype(np.int64),DEPLOY_DEN).astype(np.float32)
    def metrics(ii):
        return {'records':int(len(ii)),
                'teacher_rmse_parent_cp':float(np.sqrt(np.mean((teacher[ii]-parent_stm[ii])**2,dtype=np.float64))),
                'teacher_rmse_new_cp':float(np.sqrt(np.mean((teacher[ii]-deployed[ii])**2,dtype=np.float64))),
                'mean_abs_delta_from_parent_cp':float(np.mean(np.abs(deployed[ii]-parent_stm[ii])))}
    meta={'schema':1,'architecture':'h64-8x8-factorized-parent-plus-supported-joint-pair-ridge-residual',
          'step':a.step,'ridge':a.ridge,'min_support':a.min_support,'max_delta_q':a.max_delta_q,
          'supported_pairs':support,'metrics':{'train':metrics(train),'validation':metrics(val),'holdout':metrics(hold)},
          'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest(),'parent_sha256':hashlib.sha256(model.read_bytes()).hexdigest()}
    np.savez_compressed(a.output_dir/'student-h64-king-pair-residual.npz',feature_weights=qw0,feature_bias=qb0,output_weights=outw,output_bias=outb)
    (a.output_dir/'metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n')
    print(json.dumps(meta,indent=2,sort_keys=True))

if __name__=='__main__': main()
