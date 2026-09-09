#!/usr/bin/env python3
"""Restore Gestalt's scalar output-bias degree of freedom to the compact topology trainer.

The production Rust Gestalt topology has a quantised output bias. The first H16/H24/H32 student
trainer omitted it. This patch adds one trainable scalar and serialises it; runtime cost is one
integer addition per evaluation.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v15_gestalt_output_bias_trainer.py TRAINER.py")
p=Path(sys.argv[1]); s=p.read_text()

def rep(old,new,n=1,label=''):
    global s
    c=s.count(old)
    if c!=n: raise SystemExit(f"{label or old[:40]} count={c} expected={n}")
    s=s.replace(old,new,n)

rep(
"def forward(d,W,bias,ous,othem,ix):\n m=d['mask'][ix,:,None];aw=bias+(W[d['iw'][ix]]*m).sum(1);ab=bias+(W[d['ib'][ix]]*m).sum(1);cw=np.clip(aw,0,1);cb=np.clip(ab,0,1);hw=cw*cw;hb=cb*cb;sw=d['stmw'][ix][:,None];us=np.where(sw,hw,hb);them=np.where(sw,hb,hw);return us@ous+them@othem,(aw,ab,cw,cb,hw,hb,sw,us,them)\n",
"def forward(d,W,bias,ous,othem,obias,ix):\n m=d['mask'][ix,:,None];aw=bias+(W[d['iw'][ix]]*m).sum(1);ab=bias+(W[d['ib'][ix]]*m).sum(1);cw=np.clip(aw,0,1);cb=np.clip(ab,0,1);hw=cw*cw;hb=cb*cb;sw=d['stmw'][ix][:,None];us=np.where(sw,hw,hb);them=np.where(sw,hb,hw);return us@ous+them@othem+obias[0],(aw,ab,cw,cb,hw,hb,sw,us,them)\n",
label='forward')
rep(
"def quant(W,bias,ous,othem):return np.clip(np.rint(W*QA),-32768,32767).astype(np.int16),np.clip(np.rint(bias*QA),-32768,32767).astype(np.int16),np.clip(np.rint(ous*QB),-32768,32767).astype(np.int16),np.clip(np.rint(othem*QB),-32768,32767).astype(np.int16)\n",
"def quant(W,bias,ous,othem,obias):return np.clip(np.rint(W*QA),-32768,32767).astype(np.int16),np.clip(np.rint(bias*QA),-32768,32767).astype(np.int16),np.clip(np.rint(ous*QB),-32768,32767).astype(np.int16),np.clip(np.rint(othem*QB),-32768,32767).astype(np.int16),np.clip(np.rint(obias*QA*QB),-32768,32767).astype(np.int16)\n",
label='quant')
rep(
"def qpred(d,qW,qb,qus,qthem,ix):\n m=d['mask'][ix,:,None].astype(np.int64);aw=qb.astype(np.int64)+(qW[d['iw'][ix]].astype(np.int64)*m).sum(1);ab=qb.astype(np.int64)+(qW[d['ib'][ix]].astype(np.int64)*m).sum(1);aw=np.clip(aw,0,QA);ab=np.clip(ab,0,QA);sw=d['stmw'][ix][:,None];us=np.where(sw,aw,ab);them=np.where(sw,ab,aw);raw=((us*us)*qus.astype(np.int64)+(them*them)*qthem.astype(np.int64)).sum(1);return tdiv(tdiv(raw,QA)*CP_SCALE,QA*QB).astype(np.int32)\n",
"def qpred(d,qW,qb,qus,qthem,qobias,ix):\n m=d['mask'][ix,:,None].astype(np.int64);aw=qb.astype(np.int64)+(qW[d['iw'][ix]].astype(np.int64)*m).sum(1);ab=qb.astype(np.int64)+(qW[d['ib'][ix]].astype(np.int64)*m).sum(1);aw=np.clip(aw,0,QA);ab=np.clip(ab,0,QA);sw=d['stmw'][ix][:,None];us=np.where(sw,aw,ab);them=np.where(sw,ab,aw);raw=((us*us)*qus.astype(np.int64)+(them*them)*qthem.astype(np.int64)).sum(1);post=tdiv(raw,QA)+np.int64(qobias[0]);return tdiv(post*CP_SCALE,QA*QB).astype(np.int32)\n",
label='qpred')
rep(
"othem=rng.normal(0,.018,a.hidden).astype(np.float32);arr=[W,bias,ous,othem];opt=Adam(arr,a.lr);best=None;bestkey=(1e99,0,0);dens=(1,2,3,4,6,8,12)",
"othem=rng.normal(0,.018,a.hidden).astype(np.float32);obias=np.zeros(1,np.float32);arr=[W,bias,ous,othem,obias];opt=Adam(arr,a.lr);best=None;bestkey=(1e99,0,0);dens=(1,2,3,4,6,8,12)",
label='initialise output bias')
rep(
"pred,cache=forward(d,W,bias,ous,othem,ix);err=pred-d['target'][ix];gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix);",
"pred,cache=forward(d,W,bias,ous,othem,obias,ix);err=pred-d['target'][ix];gp=np.clip(err,-.5,.5).astype(np.float32)/len(ix);",
label='forward call')
rep(
"gb=gaw.sum(0)+gab.sum(0);gW=a.weight_decay*W.copy();mw=d['mask'][ix]",
"gb=gaw.sum(0)+gab.sum(0);gob=np.asarray([gp.sum()],dtype=np.float32);gW=a.weight_decay*W.copy();mw=d['mask'][ix]",
label='bias gradient')
rep(
"opt.step(arr,[gW,gb,gous,got])",
"opt.step(arr,[gW,gb,gous,got,gob])",
label='adam output bias')
rep(
"qW,qb,qu,qt=quant(W,bias,ous,othem);qc=qpred(d,qW,qb,qu,qt,va);",
"qW,qb,qu,qt,qob=quant(W,bias,ous,othem,obias);qc=qpred(d,qW,qb,qu,qt,qob,va);",
label='epoch quant')
rep(
"W,bias,ous,othem=best;qW,qb,qu,qt=quant(W,bias,ous,othem);den=bestkey[1];allix=np.arange(len(d['teacher']));qc=qpred(d,qW,qb,qu,qt,allix);",
"W,bias,ous,othem,obias=best;qW,qb,qu,qt,qob=quant(W,bias,ous,othem,obias);den=bestkey[1];allix=np.arange(len(d['teacher']));qc=qpred(d,qW,qb,qu,qt,qob,allix);",
label='final quant')
rep(
"np.savez_compressed(a.output_dir/f'gestalt-topology-h{a.hidden}.npz',feature_weights=qW,feature_bias=qb,output_us=qu,output_them=qt,scale_denominator=np.asarray([den],np.int32));",
"np.savez_compressed(a.output_dir/f'gestalt-topology-h{a.hidden}.npz',feature_weights=qW,feature_bias=qb,output_us=qu,output_them=qt,output_bias=qob,scale_denominator=np.asarray([den],np.int32));",
label='serialize output bias')

p.write_text(s)
