#!/usr/bin/env python3
"""Train a compact shared king-bucket NNUE-style residual student.

Each position builds two perspective accumulators from the same embedding table. King squares are
canonicalised into eight coarse buckets (rank-pair x mirrored file-pair). Ownership is relative to
the perspective, so a single 6144-row table serves both White and Black. The output is constrained
to be antisymmetric: one SCReLU head scores h(White)-h(Black). H32x2 therefore keeps the same 64
live accumulator lanes as packaged V14's absolute H64 student while carrying king-relative context.
"""
from __future__ import annotations

import argparse,json,hashlib,sys
from pathlib import Path
from typing import Any
import chess,numpy as np

QA=255;QB=64;CP_SCALE=400;TARGET_CLIP_CP=1600;FEATURES=8*768;MAX_PIECES=32


def parse_args():
    p=argparse.ArgumentParser();p.add_argument('--teacher',type=Path,required=True);p.add_argument('--engine-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--hidden',type=int,choices=(16,32),required=True);p.add_argument('--epochs',type=int,default=45);p.add_argument('--batch-size',type=int,default=256);p.add_argument('--lr',type=float,default=0.0015);p.add_argument('--weight-decay',type=float,default=2e-5);p.add_argument('--seed',type=int,default=20260908);return p.parse_args()


def feature_index(board:chess.Board,perspective:chess.Color,piece:chess.Piece,square:int)->int:
    king=board.king(perspective)
    if king is None: raise ValueError('missing king')
    kf=chess.square_file(king);kr=chess.square_rank(king)
    if not perspective: kr=7-kr
    mirror=kf>=4;ckf=7-kf if mirror else kf
    bucket=(kr//2)*2+(ckf//2)
    ownership=0 if piece.color==perspective else 1
    plane=ownership*6+(piece.piece_type-1)
    f=chess.square_file(square);r=chess.square_rank(square)
    if not perspective:r=7-r
    if mirror:f=7-f
    return bucket*768+plane*64+r*8+f


def load_engine(engine_dir:Path):
    sys.path.insert(0,str(engine_dir.resolve()))
    from experiments.numba_core import encode_position
    from experiments.numba_search import EVAL_WIDTH,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only
    return encode_position,EVAL_WIDTH,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only


def build_dataset(path:Path,engine_dir:Path):
    encode_position,EVAL_WIDTH,build_state,eval_full,eval_v13=load_engine(engine_dir)
    rec=[]
    for line in path.read_text().splitlines():
        if not line.strip():continue
        r=json.loads(line)
        if r.get('teacher_mate') is not None or abs(int(r['teacher_cp']))>5000:continue
        rec.append(r)
    n=len(rec);iw=np.zeros((n,MAX_PIECES),dtype=np.int32);ib=np.zeros_like(iw);mask=np.zeros((n,MAX_PIECES),dtype=np.float32)
    teacher=np.empty(n,dtype=np.float32);v13=np.empty(n,dtype=np.float32);v14=np.empty(n,dtype=np.float32);target=np.empty(n,dtype=np.float32);codes=np.empty(n,dtype=np.int8)
    smap={'train':0,'validation':1,'holdout':2}
    for i,r in enumerate(rec):
        b=chess.Board(r['fen']);pieces=list(b.piece_map().items());mask[i,:len(pieces)]=1.0
        for j,(sq,piece) in enumerate(pieces):
            iw[i,j]=feature_index(b,chess.WHITE,piece,sq);ib[i,j]=feature_index(b,chess.BLACK,piece,sq)
        e=encode_position(b);st=np.empty(EVAL_WIDTH,dtype=np.int32);build_state(e.board,st)
        a=float(eval_v13(e.side,st));c=float(eval_full(e.side,st));t=float(r['teacher_cp']);sign=1.0 if b.turn else -1.0
        teacher[i]=t;v13[i]=a;v14[i]=c;target[i]=sign*max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-a))/CP_SCALE;codes[i]=smap[str(r['split'])]
    return {'iw':iw,'ib':ib,'mask':mask,'teacher':teacher,'v13':v13,'v14':v14,'target':target,'codes':codes}


def rmse(a,b):return float(np.sqrt(np.mean(np.square(a.astype(np.float64)-b.astype(np.float64)))))
def mae(a,b):return float(np.mean(np.abs(a.astype(np.float64)-b.astype(np.float64))))

def forward(d,W,bias,out,idx):
    m=d['mask'][idx,:,None];aw=bias+(W[d['iw'][idx]]*m).sum(1);ab=bias+(W[d['ib'][idx]]*m).sum(1)
    cw=np.clip(aw,0.0,1.0);cb=np.clip(ab,0.0,1.0);hw=cw*cw;hb=cb*cb
    return (hw-hb)@out,(aw,ab,cw,cb,hw,hb)


def quantize(W,bias,out):
    return np.clip(np.rint(W*QA),-32768,32767).astype(np.int16),np.clip(np.rint(bias*QA),-32768,32767).astype(np.int16),np.clip(np.rint(out*QB),-32768,32767).astype(np.int16)

def tdiv(v,d):
    v=np.asarray(v,dtype=np.int64);return np.where(v>=0,v//d,-((-v)//d))
def quant_pred_cp(d,qW,qb,qo,idx):
    m=d['mask'][idx,:,None].astype(np.int64);aw=qb.astype(np.int64)+(qW[d['iw'][idx]].astype(np.int64)*m).sum(1);ab=qb.astype(np.int64)+(qW[d['ib'][idx]].astype(np.int64)*m).sum(1)
    aw=np.clip(aw,0,QA);ab=np.clip(ab,0,QA);raw=((aw*aw-ab*ab)*qo.astype(np.int64)).sum(1);scaled=tdiv(raw,QA);return tdiv(scaled*CP_SCALE,QA*QB).astype(np.int32)


class Adam:
    def __init__(self,arrs,lr):self.lr=lr;self.m=[np.zeros_like(a) for a in arrs];self.v=[np.zeros_like(a) for a in arrs];self.t=0
    def step(self,arrs,grads):
        self.t+=1;b1=.9;b2=.999;c1=1-b1**self.t;c2=1-b2**self.t
        for i,(a,g) in enumerate(zip(arrs,grads)):
            self.m[i]=b1*self.m[i]+(1-b1)*g;self.v[i]=b2*self.v[i]+(1-b2)*(g*g);a-=self.lr*(self.m[i]/c1)/(np.sqrt(self.v[i]/c2)+1e-8)


def corrected_metrics(d,idx,corr_cp,den):
    # corr_cp is White-perspective; teacher/V13 are side-to-move. Recover side sign from target's
    # relation by reparsing nothing: target_abs sign convention means candidate STM correction is
    # simply target architecture output multiplied by +1 for White-to-move/-1 for Black-to-move.
    # Store signs explicitly at construction in the final version below.
    sign=d['sign'][idx];cand=d['v13'][idx]+sign*np.asarray(corr_cp,dtype=np.float64)/float(den)
    return {'records':int(len(idx)),'current_v14_rmse_cp':rmse(d['teacher'][idx],d['v14'][idx]),'candidate_rmse_cp':rmse(d['teacher'][idx],cand),'v13_rmse_cp':rmse(d['teacher'][idx],d['v13'][idx]),'current_v14_mae_cp':mae(d['teacher'][idx],d['v14'][idx]),'candidate_mae_cp':mae(d['teacher'][idx],cand)}


def main():
    a=parse_args();a.output_dir.mkdir(parents=True,exist_ok=False);d=build_dataset(a.teacher,a.engine_dir)
    # Recover side signs cheaply from teacher records in identical filtered order.
    signs=[]
    for line in a.teacher.read_text().splitlines():
        if not line.strip():continue
        r=json.loads(line)
        if r.get('teacher_mate') is not None or abs(int(r['teacher_cp']))>5000:continue
        signs.append(1.0 if chess.Board(r['fen']).turn else -1.0)
    d['sign']=np.asarray(signs,dtype=np.float32)
    tr=np.flatnonzero(d['codes']==0);va=np.flatnonzero(d['codes']==1);ho=np.flatnonzero(d['codes']==2);rng=np.random.default_rng(a.seed+a.hidden)
    W=rng.normal(0,.012,size=(FEATURES,a.hidden)).astype(np.float32);bias=np.full(a.hidden,.10,dtype=np.float32);out=rng.normal(0,.018,size=a.hidden).astype(np.float32);arr=[W,bias,out];opt=Adam(arr,a.lr)
    best=None;best_key=(float('inf'),0,0);history=[];dens=(1,2,4,6,8,12)
    for ep in range(1,a.epochs+1):
        order=rng.permutation(tr);loss=0.0
        for start in range(0,len(order),a.batch_size):
            ix=order[start:start+a.batch_size];pred,cache=forward(d,W,bias,out,ix);err=pred-d['target'][ix];gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix);loss+=float(np.abs(err).sum())
            aw,ab,cw,cb,hw,hb=cache;go=(hw-hb).T@gp+a.weight_decay*out;ghw=gp[:,None]*out[None,:];ghb=-ghw;gaw=ghw*(2*cw)*((aw>0)&(aw<1));gab=ghb*(2*cb)*((ab>0)&(ab<1));gb=gaw.sum(0)+gab.sum(0)
            gW=a.weight_decay*W.copy();mw=d['mask'][ix]
            for row in range(len(ix)):
                np.add.at(gW,d['iw'][ix[row]][mw[row]>0],gaw[row]);np.add.at(gW,d['ib'][ix[row]][mw[row]>0],gab[row])
            opt.step(arr,[gW,gb,go])
        qW,qb,qo=quantize(W,bias,out);qcp=quant_pred_cp(d,qW,qb,qo,va);sign=d['sign'][va]
        cand=[]
        for den in dens:
            score=d['v13'][va]+sign*qcp/den;cand.append((rmse(d['teacher'][va],score),den))
        val,den=min(cand);row={'epoch':ep,'validation_quant_rmse_cp':val,'best_denominator':den,'mean_abs_train_target_error':loss/max(1,len(tr))};history.append(row);print(json.dumps(row),flush=True)
        key=(val,den,ep)
        if val<best_key[0]:best_key=key;best=(W.copy(),bias.copy(),out.copy())
    assert best is not None;W,bias,out=best;qW,qb,qo=quantize(W,bias,out);den=best_key[1]
    all_idx=np.arange(len(d['teacher']));qall=quant_pred_cp(d,qW,qb,qo,all_idx)
    metrics={'train':corrected_metrics(d,tr,qall[tr],den),'validation':corrected_metrics(d,va,qall[va],den),'holdout':corrected_metrics(d,ho,qall[ho],den)}
    meta={'architecture':f'kingbucket8-shared-h{a.hidden}x2-antisymmetric-screlu','hidden_per_perspective':a.hidden,'live_accumulator_lanes':2*a.hidden,'feature_rows':FEATURES,'model_int16_bytes':int(qW.nbytes+qb.nbytes+qo.nbytes),'best_epoch':best_key[2],'selected_scale_denominator':den,'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest(),'records':int(len(all_idx)),'metrics':metrics,'history':history}
    np.savez_compressed(a.output_dir/f'bucket-h{a.hidden}.npz',feature_weights=qW,feature_bias=qb,output_weights=qo,scale_denominator=np.asarray([den],dtype=np.int32));(a.output_dir/'training-metadata.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n');print('FINAL',json.dumps({k:v for k,v in meta.items() if k!='history'},sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
