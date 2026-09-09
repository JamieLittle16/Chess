#!/usr/bin/env python3
"""Fine-tune V14's existing H64 output head on Rust alpha/beta decision events.

The feature transformer is frozen byte-for-byte. Candidate models therefore have exactly the same
runtime shape/cost as packaged V14; only the 64 quantised output weights are allowed to move by a
small bounded number of integer steps. Selection is by held-out alpha/beta decision agreement, not
pointwise centipawn RMSE.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import chess
import numpy as np

QA=255
QB=64
CP_SCALE=400
STUDENT_DEN=12
MATE_THRESHOLD=30000


def trunc_div(v:np.ndarray|int,d:int):
    a=np.asarray(v,dtype=np.int64)
    out=np.where(a>=0,a//d,-((-a)//d))
    return int(out) if out.ndim==0 else out


def load_engine(d:Path):
    sys.path.insert(0,str(d.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH,STUDENT_OFFSET,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only
    return encode_position,EVAL_WIDTH,STUDENT_OFFSET,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only


def exact_student(x2:np.ndarray,w:np.ndarray,bias:int,sign:np.ndarray)->np.ndarray:
    raw=x2.astype(np.int64)@w.astype(np.int64)
    scaled=trunc_div(raw,QA)+int(bias)
    white=trunc_div(scaled*CP_SCALE,QA*QB)
    signed=white*sign.astype(np.int64)
    return trunc_div(signed,STUDENT_DEN).astype(np.int32)


def decision_metrics(rows:list[dict],idx:np.ndarray,pred:np.ndarray)->dict[str,float|int]:
    t=np.asarray([rows[i]['teacher_cp'] for i in idx],np.int32)
    a=np.asarray([rows[i]['alpha'] for i in idx],np.int32)
    b=np.asarray([rows[i]['beta'] for i in idx],np.int32)
    p=pred[idx]
    out:dict[str,float|int]={}
    for name,thr,strict in [('beta',b,False),('alpha',a,True)]:
        finite=np.abs(thr)<MATE_THRESHOLD
        teacher=(t>thr) if strict else (t>=thr)
        cand=(p>thr) if strict else (p>=thr)
        if finite.any():
            out[f'{name}_agreement']=float(np.mean(teacher[finite]==cand[finite]))
            near=finite & (np.abs(t-thr)<=150)
            out[f'{name}_near_records']=int(near.sum())
            out[f'{name}_near_agreement']=float(np.mean(teacher[near]==cand[near])) if near.any() else 1.0
        else:
            out[f'{name}_agreement']=1.0;out[f'{name}_near_records']=0;out[f'{name}_near_agreement']=1.0
    diff=p.astype(np.float64)-t.astype(np.float64)
    out['rmse_cp']=float(np.sqrt(np.mean(diff*diff)))
    out['mae_cp']=float(np.mean(np.abs(diff)))
    return out


def metric_key(m:dict[str,float|int])->float:
    return (4.0*(1-float(m['beta_near_agreement']))
            +2.0*(1-float(m['alpha_near_agreement']))
            +1.0*(1-float(m['beta_agreement']))
            +0.5*(1-float(m['alpha_agreement']))
            +0.00005*float(m['rmse_cp']))


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--corpus',type=Path,required=True);ap.add_argument('--engine-dir',type=Path,required=True)
    ap.add_argument('--output-dir',type=Path,required=True);ap.add_argument('--max-records',type=int,default=180000)
    a=ap.parse_args();a.output_dir.mkdir(parents=True,exist_ok=False)
    rows=[json.loads(x) for x in a.corpus.read_text().splitlines() if x.strip()]
    if len(rows)>a.max_records:
        # Deterministic frequency-preserving thinning, independent of labels/split.
        step=len(rows)/a.max_records;rows=[rows[int(i*step)] for i in range(a.max_records)]
    enc,W,off,build,full,v13f=load_engine(a.engine_dir)
    model_path=a.engine_dir/'experiments/v14_student_h64.npz';model=np.load(model_path,allow_pickle=False)
    fw=np.ascontiguousarray(model['feature_weights'],dtype=np.int16);fb=np.ascontiguousarray(model['feature_bias'],dtype=np.int16)
    w0=np.ascontiguousarray(model['output_weights'],dtype=np.int16);bias=int(np.asarray(model['output_bias']).reshape(-1)[0])
    if fw.shape!=(768,64) or fb.shape!=(64,) or w0.shape!=(64,): raise ValueError('unexpected V14 H64 model')

    n=len(rows);x2=np.empty((n,64),np.int32);v13=np.empty(n,np.int32);base=np.empty(n,np.int32);sign=np.empty(n,np.int8)
    for i,r in enumerate(rows):
        b=chess.Board(r['fen']);e=enc(b);st=np.empty(W,np.int32);build(e.board,st)
        act=np.clip(st[off:off+64],0,QA).astype(np.int32);x2[i]=act*act
        v13[i]=int(v13f(e.side,st));base[i]=int(full(e.side,st));sign[i]=1 if b.turn==chess.WHITE else -1
        if (i+1)%20000==0: print(json.dumps({'encoded':i+1,'records':n}),flush=True)

    split=np.asarray([r['split'] for r in rows]);tr=np.flatnonzero(split=='train');va=np.flatnonzero(split=='validation');ho=np.flatnonzero(split=='holdout')
    teacher=np.asarray([r['teacher_cp'] for r in rows],np.float64)
    alpha=np.asarray([r['alpha'] for r in rows],np.float64);beta=np.asarray([r['beta'] for r in rows],np.float64)
    kind=np.asarray([r['kind'] for r in rows])
    weights=np.ones(n,np.float64)
    weights*=np.asarray([{'rfp':3.0,'qstand':2.0,'qstable':1.0,'qceil':1.25,'qpath':1.0}[k] for k in kind])
    fbmask=np.abs(beta)<MATE_THRESHOLD;famask=np.abs(alpha)<MATE_THRESHOLD
    weights*=1+6*np.exp(-np.abs(teacher-beta)/120)*fbmask+3*np.exp(-np.abs(teacher-alpha)/120)*famask
    # Hard current-search decision disagreements deserve extra mass.
    tbc=(teacher>=beta);bbc=(base>=beta);tar=(teacher>alpha);bar=(base>alpha)
    weights*=1+2*(fbmask&(tbc!=bbc))+1*(famask&(tar!=bar))
    weights=np.clip(weights,1,24)

    coeff=CP_SCALE/(QA*QA*QB*STUDENT_DEN)
    X=x2.astype(np.float64)*coeff*sign[:,None].astype(np.float64)
    y=teacher-v13.astype(np.float64)
    original_student=exact_student(x2,w0,bias,sign)
    reconstructed=v13+original_student
    exact_mismatch=int(np.max(np.abs(reconstructed-base)))
    if exact_mismatch!=0: raise AssertionError(f'exact baseline reconstruction mismatch {exact_mismatch}')

    baseline={'validation':decision_metrics(rows,va,base),'holdout':decision_metrics(rows,ho,base)}
    print('BASELINE',json.dumps(baseline,sort_keys=True),flush=True)
    ridge_scales=(0.03,0.1,0.3,1.0,3.0,10.0)
    candidates=[]
    Xt=X[tr];yt=y[tr];wt=weights[tr]
    sw=np.sqrt(wt);Xw=Xt*sw[:,None];yw=yt*sw
    gram=Xw.T@Xw;rhs=Xw.T@yw;diag=float(np.mean(np.diag(gram)))
    eye=np.eye(64)
    for ridge_scale in ridge_scales:
        lam=max(1e-9,ridge_scale*diag)
        # Ridge around the original quantised head, not around zero.
        fitted=np.linalg.solve(gram+lam*eye,rhs+lam*w0.astype(np.float64))
        for max_step in (1,2,3):
            lo=w0.astype(np.int32)-max_step;hi=w0.astype(np.int32)+max_step
            qw=np.clip(np.rint(fitted).astype(np.int32),lo,hi).astype(np.int16)
            pred=v13+exact_student(x2,qw,bias,sign)
            vm=decision_metrics(rows,va,pred);hm=decision_metrics(rows,ho,pred)
            shift=float(np.mean(np.abs(pred.astype(np.float64)-base.astype(np.float64))))
            candidates.append({'ridge_scale':ridge_scale,'max_step':max_step,'weights':qw,'validation':vm,'holdout':hm,'mean_abs_shift_cp':shift,'key':metric_key(vm)})
            print('CANDIDATE',json.dumps({k:v for k,v in candidates[-1].items() if k!='weights'},sort_keys=True),flush=True)

    selected=[]
    for max_step in (1,2,3):
        best=min((c for c in candidates if c['max_step']==max_step),key=lambda c:c['key'])
        selected.append(best)
        np.savez_compressed(a.output_dir/f'decision-head-step{max_step}.npz',feature_weights=fw,feature_bias=fb,output_weights=best['weights'],output_bias=np.asarray([bias],np.int32))
    overall=min(selected,key=lambda c:c['key'])
    np.savez_compressed(a.output_dir/'decision-head-best.npz',feature_weights=fw,feature_bias=fb,output_weights=overall['weights'],output_bias=np.asarray([bias],np.int32))
    meta={'schema':'v16-decision-aware-h64-head-v1','records':n,'split_counts':{s:int(np.sum(split==s)) for s in ('train','validation','holdout')},
          'corpus_sha256':hashlib.sha256(a.corpus.read_bytes()).hexdigest(),'source_model_sha256':hashlib.sha256(model_path.read_bytes()).hexdigest(),
          'baseline':baseline,'selected':[{k:v for k,v in c.items() if k!='weights'} for c in selected],
          'overall_best':{k:v for k,v in overall.items() if k!='weights'},'output_weight_changes':(overall['weights'].astype(int)-w0.astype(int)).tolist()}
    (a.output_dir/'metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n');print('FINAL',json.dumps(meta,sort_keys=True),flush=True)
    return 0


if __name__=='__main__': raise SystemExit(main())
