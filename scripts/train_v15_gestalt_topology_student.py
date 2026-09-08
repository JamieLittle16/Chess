#!/usr/bin/env python3
from __future__ import annotations
import argparse,hashlib,json,sys
from pathlib import Path
import chess,numpy as np
QA=255;QB=64;CP_SCALE=400;TARGET_CLIP_CP=1800;BUCKETS=9;FEATURES=BUCKETS*768;MAX_PIECES=32
BUCKET_MAP=np.asarray([
0,1,2,3,12,11,10,9, 4,4,5,5,14,14,13,13, 6,6,6,6,15,15,15,15,
7,7,7,7,16,16,16,16, 8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17,
8,8,8,8,17,17,17,17, 8,8,8,8,17,17,17,17],dtype=np.int16)

def args():
 p=argparse.ArgumentParser();p.add_argument('--teacher',type=Path,required=True);p.add_argument('--engine-dir',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--hidden',type=int,choices=(12,16,24,32),required=True);p.add_argument('--epochs',type=int,default=30);p.add_argument('--batch-size',type=int,default=256);p.add_argument('--lr',type=float,default=.0015);p.add_argument('--weight-decay',type=float,default=2e-5);p.add_argument('--seed',type=int,default=20260908);return p.parse_args()

def feature_index(b,perspective,piece,sq):
 k=b.king(perspective)
 if k is None:raise ValueError('missing king')
 mapped=k if perspective else chess.square(chess.square_file(k),7-chess.square_rank(k));raw=int(BUCKET_MAP[mapped]);bucket=raw%BUCKETS;mirror=chess.square_file(k)>=4
 f=chess.square_file(sq);r=chess.square_rank(sq)
 if mirror:f=7-f
 if not perspective:r=7-r
 ownership=0 if piece.color==perspective else 1;plane=ownership*6+(piece.piece_type-1)
 return bucket*768+plane*64+r*8+f

def load_engine(d):
 sys.path.insert(0,str(d.resolve()));from experiments.numba_core import encode_position;from experiments.numba_search import EVAL_WIDTH,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only;return encode_position,EVAL_WIDTH,_build_eval_state_into,_evaluate_state,_evaluate_state_v13_only

def dataset(path,engine):
 enc,W,build,full,v13f=load_engine(engine);rows=[]
 for line in path.read_text().splitlines():
  if not line.strip():continue
  r=json.loads(line)
  if r.get('teacher_mate') is None and abs(int(r['teacher_cp']))<=5000:rows.append(r)
 n=len(rows);iw=np.zeros((n,MAX_PIECES),np.int32);ib=np.zeros_like(iw);mask=np.zeros((n,MAX_PIECES),np.float32);teacher=np.empty(n,np.float32);v13=np.empty(n,np.float32);v14=np.empty(n,np.float32);target=np.empty(n,np.float32);stmw=np.empty(n,np.bool_);codes=np.empty(n,np.int8);smap={'train':0,'validation':1,'holdout':2}
 for i,r in enumerate(rows):
  b=chess.Board(r['fen']);pcs=list(b.piece_map().items());mask[i,:len(pcs)]=1
  for j,(sq,p) in enumerate(pcs):iw[i,j]=feature_index(b,chess.WHITE,p,sq);ib[i,j]=feature_index(b,chess.BLACK,p,sq)
  e=enc(b);st=np.empty(W,np.int32);build(e.board,st);a=float(v13f(e.side,st));c=float(full(e.side,st));t=float(r['teacher_cp']);teacher[i]=t;v13[i]=a;v14[i]=c;target[i]=max(-TARGET_CLIP_CP,min(TARGET_CLIP_CP,t-a))/CP_SCALE;stmw[i]=bool(b.turn);codes[i]=smap[r['split']]
 return {'iw':iw,'ib':ib,'mask':mask,'teacher':teacher,'v13':v13,'v14':v14,'target':target,'stmw':stmw,'codes':codes}
def rmse(a,b):return float(np.sqrt(np.mean(np.square(a.astype(np.float64)-b.astype(np.float64)))))
def mae(a,b):return float(np.mean(np.abs(a.astype(np.float64)-b.astype(np.float64))))
def forward(d,W,bias,ous,othem,ix):
 m=d['mask'][ix,:,None];aw=bias+(W[d['iw'][ix]]*m).sum(1);ab=bias+(W[d['ib'][ix]]*m).sum(1);cw=np.clip(aw,0,1);cb=np.clip(ab,0,1);hw=cw*cw;hb=cb*cb;sw=d['stmw'][ix][:,None];us=np.where(sw,hw,hb);them=np.where(sw,hb,hw);return us@ous+them@othem,(aw,ab,cw,cb,hw,hb,sw,us,them)
def quant(W,bias,ous,othem):return np.clip(np.rint(W*QA),-32768,32767).astype(np.int16),np.clip(np.rint(bias*QA),-32768,32767).astype(np.int16),np.clip(np.rint(ous*QB),-32768,32767).astype(np.int16),np.clip(np.rint(othem*QB),-32768,32767).astype(np.int16)
def tdiv(v,d):v=np.asarray(v,np.int64);return np.where(v>=0,v//d,-((-v)//d))
def qpred(d,qW,qb,qus,qthem,ix):
 m=d['mask'][ix,:,None].astype(np.int64);aw=qb.astype(np.int64)+(qW[d['iw'][ix]].astype(np.int64)*m).sum(1);ab=qb.astype(np.int64)+(qW[d['ib'][ix]].astype(np.int64)*m).sum(1);aw=np.clip(aw,0,QA);ab=np.clip(ab,0,QA);sw=d['stmw'][ix][:,None];us=np.where(sw,aw,ab);them=np.where(sw,ab,aw);raw=((us*us)*qus.astype(np.int64)+(them*them)*qthem.astype(np.int64)).sum(1);return tdiv(tdiv(raw,QA)*CP_SCALE,QA*QB).astype(np.int32)
class Adam:
 def __init__(self,arr,lr):self.lr=lr;self.m=[np.zeros_like(x) for x in arr];self.v=[np.zeros_like(x) for x in arr];self.t=0
 def step(self,arr,g):
  self.t+=1;b1=.9;b2=.999;c1=1-b1**self.t;c2=1-b2**self.t
  for i,(a,x) in enumerate(zip(arr,g)):self.m[i]=b1*self.m[i]+(1-b1)*x;self.v[i]=b2*self.v[i]+(1-b2)*x*x;a-=self.lr*(self.m[i]/c1)/(np.sqrt(self.v[i]/c2)+1e-8)
def metrics(d,ix,qcp,den):
 cand=d['v13'][ix]+qcp/den;return {'records':int(len(ix)),'current_v14_rmse_cp':rmse(d['teacher'][ix],d['v14'][ix]),'candidate_rmse_cp':rmse(d['teacher'][ix],cand),'v13_rmse_cp':rmse(d['teacher'][ix],d['v13'][ix]),'current_v14_mae_cp':mae(d['teacher'][ix],d['v14'][ix]),'candidate_mae_cp':mae(d['teacher'][ix],cand)}
def main():
 a=args();a.output_dir.mkdir(parents=True,exist_ok=False);d=dataset(a.teacher,a.engine_dir);tr=np.flatnonzero(d['codes']==0);va=np.flatnonzero(d['codes']==1);ho=np.flatnonzero(d['codes']==2);rng=np.random.default_rng(a.seed+a.hidden);W=rng.normal(0,.012,(FEATURES,a.hidden)).astype(np.float32);bias=np.full(a.hidden,.1,np.float32);ous=rng.normal(0,.018,a.hidden).astype(np.float32);othem=rng.normal(0,.018,a.hidden).astype(np.float32);arr=[W,bias,ous,othem];opt=Adam(arr,a.lr);best=None;bestkey=(1e99,0,0);dens=(1,2,3,4,6,8,12)
 for ep in range(1,a.epochs+1):
  order=rng.permutation(tr);loss=0.
  for st in range(0,len(order),a.batch_size):
   ix=order[st:st+a.batch_size];pred,cache=forward(d,W,bias,ous,othem,ix);err=pred-d['target'][ix];gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix);loss+=float(np.abs(err).sum());aw,ab,cw,cb,hw,hb,sw,us,them=cache;gous=us.T@gp+a.weight_decay*ous;got=them.T@gp+a.weight_decay*othem;gus=gp[:,None]*ous[None,:];gth=gp[:,None]*othem[None,:];ghw=np.where(sw,gus,gth);ghb=np.where(sw,gth,gus);gaw=ghw*(2*cw)*((aw>0)&(aw<1));gab=ghb*(2*cb)*((ab>0)&(ab<1));gb=gaw.sum(0)+gab.sum(0);gW=a.weight_decay*W.copy();mw=d['mask'][ix]
   for r in range(len(ix)):np.add.at(gW,d['iw'][ix[r]][mw[r]>0],gaw[r]);np.add.at(gW,d['ib'][ix[r]][mw[r]>0],gab[r])
   opt.step(arr,[gW,gb,gous,got])
  qW,qb,qu,qt=quant(W,bias,ous,othem);qc=qpred(d,qW,qb,qu,qt,va);cand=[(rmse(d['teacher'][va],d['v13'][va]+qc/den),den) for den in dens];val,den=min(cand);print(json.dumps({'epoch':ep,'validation_rmse_cp':val,'den':den,'train_abs':loss/max(1,len(tr))}),flush=True)
  if val<bestkey[0]:bestkey=(val,den,ep);best=tuple(x.copy() for x in arr)
 W,bias,ous,othem=best;qW,qb,qu,qt=quant(W,bias,ous,othem);den=bestkey[1];allix=np.arange(len(d['teacher']));qc=qpred(d,qW,qb,qu,qt,allix);meta={'architecture':f'gestalt9-shared-h{a.hidden}x2-separate-us-them','hidden':a.hidden,'live_lanes':2*a.hidden,'feature_rows':FEATURES,'model_int16_bytes':int(qW.nbytes+qb.nbytes+qu.nbytes+qt.nbytes),'best_epoch':bestkey[2],'den':den,'records':int(len(allix)),'metrics':{'train':metrics(d,tr,qc[tr],den),'validation':metrics(d,va,qc[va],den),'holdout':metrics(d,ho,qc[ho],den)},'teacher_sha256':hashlib.sha256(a.teacher.read_bytes()).hexdigest()};np.savez_compressed(a.output_dir/f'gestalt-topology-h{a.hidden}.npz',feature_weights=qW,feature_bias=qb,output_us=qu,output_them=qt,scale_denominator=np.asarray([den],np.int32));(a.output_dir/'metadata.json').write_text(json.dumps(meta,indent=2)+'\n');print('FINAL',json.dumps(meta));
if __name__=='__main__':main()
