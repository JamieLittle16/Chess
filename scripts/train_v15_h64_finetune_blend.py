#!/usr/bin/env python3
"""Fine-tune packaged V14's exact H64 student toward a blended Rust-Gestalt target.

Unlike the earlier replacement students, this starts from the *actual quantized V14 parameters* and
keeps the identical absolute768 -> H64 SCReLU topology.  The runtime therefore does not change; only
the evaluator weights move.  A small anchor penalty keeps the learned correction close to the search-
compatible V14 model while the blended teacher injects a controlled amount of Rust V15 information.
"""
from __future__ import annotations

import argparse, hashlib, json, sys
from pathlib import Path
import chess
import numpy as np

INPUTS=768; HIDDEN=64; QA=255; QB=64; CP_SCALE=400; TARGET_CLIP_CP=1600


def args():
    p=argparse.ArgumentParser()
    p.add_argument('--teacher',type=Path,required=True); p.add_argument('--engine-dir',type=Path,required=True)
    p.add_argument('--init-model',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=16); p.add_argument('--batch-size',type=int,default=512)
    p.add_argument('--lr',type=float,default=3e-4); p.add_argument('--anchor',type=float,default=2e-3)
    p.add_argument('--seed',type=int,default=20260908); return p.parse_args()


def fi(piece:chess.Piece,sq:int)->int: return (0 if piece.color else 384)+(piece.piece_type-1)*64+sq

def tdiv(v,d):
    v=np.asarray(v,dtype=np.int64); return np.where(v>=0,v//d,-((-v)//d))

def quantize(w0,b0,w1,b1):
    return (np.clip(np.rint(w0*QA),-32768,32767).astype(np.int16),np.clip(np.rint(b0*QA),-32768,32767).astype(np.int16),np.clip(np.rint(w1*QB),-32768,32767).astype(np.int16),np.clip(np.rint(b1*QA*QB),-(2**31),2**31-1).astype(np.int32))

def qpred(x,qw0,qb0,qw1,qb1):
    a=x.astype(np.int32)@qw0.astype(np.int32)+qb0.astype(np.int32); a=np.clip(a,0,QA).astype(np.int64)
    raw=(a*a)@qw1.astype(np.int64); scaled=tdiv(raw,QA)+int(qb1[0]); return tdiv(scaled*CP_SCALE,QA*QB).astype(np.int32)

def rmse(a,b): return float(np.sqrt(np.mean(np.square(a.astype(np.float64)-b.astype(np.float64)))))
def mae(a,b): return float(np.mean(np.abs(a.astype(np.float64)-b.astype(np.float64))))


def dataset(path,engine_dir):
    sys.path.insert(0,str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH,_build_eval_state_into,_evaluate_state_v13_only
    rows=[]
    for line in path.read_text().splitlines():
        if not line.strip(): continue
        r=json.loads(line)
        if r.get('teacher_mate') is not None or abs(int(r['teacher_cp']))>5000: continue
        rows.append(r)
    n=len(rows); x=np.zeros((n,INPUTS),np.float32); y=np.empty(n,np.float32); base=np.empty(n,np.float32); sign=np.empty(n,np.float32); code=np.empty(n,np.int8); v14=np.empty(n,np.float32); gestalt=np.empty(n,np.float32)
    sm={'train':0,'validation':1,'holdout':2}
    for i,r in enumerate(rows):
        b=chess.Board(r['fen'])
        for sq,p in b.piece_map().items(): x[i,fi(p,sq)]=1.0
        e=encode_position(b); st=np.empty(EVAL_WIDTH,np.int32); _build_eval_state_into(e.board,st)
        bv=float(_evaluate_state_v13_only(e.side,st)); s=1.0 if b.turn else -1.0; target=float(r['teacher_cp'])
        base[i]=bv; sign[i]=s; v14[i]=float(r.get('v14_cp',target)); gestalt[i]=float(r.get('gestalt_cp',target)); y[i]=s*max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,target-bv))/CP_SCALE; code[i]=sm[str(r['split'])]
    return x,y,base,sign,code,v14,gestalt


class Adam:
    def __init__(self,arr,lr): self.lr=lr; self.m=[np.zeros_like(a) for a in arr]; self.v=[np.zeros_like(a) for a in arr]; self.t=0
    def step(self,arr,gr):
        self.t+=1; b1=.9; b2=.999; c1=1-b1**self.t; c2=1-b2**self.t
        for i,(a,g) in enumerate(zip(arr,gr)):
            self.m[i]=b1*self.m[i]+(1-b1)*g; self.v[i]=b2*self.v[i]+(1-b2)*(g*g); a-=self.lr*(self.m[i]/c1)/(np.sqrt(self.v[i]/c2)+1e-8)


def metrics(mask,teacher,gestalt,v14,base,sign,pred):
    cand=base[mask]+sign[mask]*pred[mask]
    drift=np.abs(cand-v14[mask])
    return {'records':int(mask.sum()),'v14_to_blend_rmse_cp':rmse(teacher[mask],v14[mask]),'candidate_to_blend_rmse_cp':rmse(teacher[mask],cand),'v14_to_gestalt_rmse_cp':rmse(gestalt[mask],v14[mask]),'candidate_to_gestalt_rmse_cp':rmse(gestalt[mask],cand),'candidate_vs_v14_mae_cp':mae(cand,v14[mask]),'candidate_vs_v14_p95_abs_cp':float(np.percentile(drift,95))}


def main():
    a=args(); a.output_dir.mkdir(parents=True,exist_ok=False)
    x,y,base,sign,code,v14,gestalt=dataset(a.teacher,a.engine_dir); teacher=np.empty_like(base)
    # blended teacher can be reconstructed from target + V13 baseline exactly enough for metrics
    teacher[:] = base + sign*y*CP_SCALE
    z=np.load(a.init_model); qw0=z['feature_weights']; qb0=z['feature_bias']; qw1=z['output_weights']; qb1=z['output_bias']
    if qw0.shape!=(INPUTS,HIDDEN): raise SystemExit(f'unexpected init model shape {qw0.shape}')
    w0=qw0.astype(np.float32)/QA; b0=qb0.astype(np.float32)/QA; w1=qw1.astype(np.float32)/QB; b1=qb1.astype(np.float32)/(QA*QB)
    init=[w0.copy(),b0.copy(),w1.copy(),b1.copy()]; arr=[w0,b0,w1,b1]; opt=Adam(arr,a.lr); rng=np.random.default_rng(a.seed)
    tr=np.flatnonzero(code==0); va=code==1; ho=code==2; best=None; best_score=1e30; history=[]
    for ep in range(1,a.epochs+1):
        order=rng.permutation(tr); loss=0.0
        for start in range(0,len(order),a.batch_size):
            ix=order[start:start+a.batch_size]; xb=x[ix]; yb=y[ix]; zz=xb@w0+b0; c=np.clip(zz,0,1); h=c*c; pred=h@w1+b1[0]; err=pred-yb; gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix); loss+=float(np.abs(err).sum())
            gw1=h.T@gp + a.anchor*(w1-init[2]); gb1=np.asarray([gp.sum()],np.float32)+a.anchor*(b1-init[3]); gh=gp[:,None]*w1[None,:]; gz=gh*(2*c)*((zz>0)&(zz<1)); gw0=xb.T@gz+a.anchor*(w0-init[0]); gb0=gz.sum(0)+a.anchor*(b0-init[1]); opt.step(arr,[gw0,gb0,gw1,gb1])
        q=quantize(w0,b0,w1,b1); qp=qpred(x,*q); cand=base[va]+sign[va]*qp[va]; score=rmse(teacher[va],cand); row={'epoch':ep,'validation_blend_rmse_cp':score,'mean_abs_train_error':loss/max(1,len(tr))}; history.append(row); print(json.dumps(row),flush=True)
        if score<best_score: best_score=score; best=[v.copy() for v in arr]
    assert best is not None; w0[:],b0[:],w1[:],b1[:]=best; q=quantize(w0,b0,w1,b1); qp=qpred(x,*q)
    meta={'architecture':'absolute768-single-64-screlu-v14-finetune','runtime_topology_changed':False,'init_model_sha256':hashlib.sha256(a.init_model.read_bytes()).hexdigest(),'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest(),'lr':a.lr,'anchor':a.anchor,'best_validation_blend_rmse_cp':best_score,'metrics':{'validation':metrics(va,teacher,gestalt,v14,base,sign,qp),'holdout':metrics(ho,teacher,gestalt,v14,base,sign,qp)},'history':history}
    np.savez_compressed(a.output_dir/'v14_student_h64.npz',feature_weights=q[0],feature_bias=q[1],output_weights=q[2],output_bias=q[3]); (a.output_dir/'training-metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n'); print('FINAL',json.dumps({k:v for k,v in meta.items() if k!='history'},sort_keys=True)); return 0

if __name__=='__main__': raise SystemExit(main())
