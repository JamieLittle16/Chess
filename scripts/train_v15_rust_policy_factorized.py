#!/usr/bin/env python3
from __future__ import annotations
import argparse,json
from pathlib import Path
import chess,numpy as np,torch
from torch import nn
PLANES=12; BOARD_FEATURES=12*64+5; MOVE_FEATURES=64+64+6+6+5+4

def board_features(b):
    x=np.zeros(BOARD_FEATURES,dtype=np.float32)
    for sq,p in b.piece_map().items(): x[((0 if p.color else 6)+p.piece_type-1)*64+sq]=1.0
    o=768;x[o]=1.0 if b.turn else -1.0;x[o+1]=float(b.has_kingside_castling_rights(chess.WHITE));x[o+2]=float(b.has_queenside_castling_rights(chess.WHITE));x[o+3]=float(b.has_kingside_castling_rights(chess.BLACK));x[o+4]=float(b.has_queenside_castling_rights(chess.BLACK));return x

def move_features(b,m):
    x=np.zeros(MOVE_FEATURES,dtype=np.float32);o=0;x[m.from_square]=1;o=64;x[o+m.to_square]=1;o+=64;p=b.piece_at(m.from_square)
    if p:x[o+p.piece_type-1]=1
    o+=6;c=b.piece_at(m.to_square)
    if b.is_en_passant(m):x[o]=1
    elif c:x[o+c.piece_type-1]=1
    o+=6
    if m.promotion:x[o+m.promotion-1]=1
    o+=5;x[o]=float(b.is_capture(m));x[o+1]=0.;x[o+2]=float(b.is_castling(m));x[o+3]=float(b.is_en_passant(m));return x

def load_rows(path):
    rows=[]
    for line in path.read_text().splitlines():
        if not line.strip():continue
        r=json.loads(line);b=chess.Board(r['fen']);legal={m.uci() for m in b.legal_moves};cs=[(str(c['move']),int(c['score'])) for c in r.get('candidates',[]) if str(c['move']) in legal]
        if cs:cs.sort(key=lambda z:-z[1]);rows.append((r.get('split','train'),r['fen'],cs))
    return rows

def target(legal,cs,temp=60.,maxgap=600.):
    y=torch.zeros(len(legal));best=cs[0][1];loc={m:i for i,m in enumerate(legal)};ix=[];g=[]
    for m,s in cs:
        if m in loc:ix.append(loc[m]);g.append(max(-maxgap,float(s-best))/temp)
    w=torch.softmax(torch.tensor(g),0)
    for i,v in zip(ix,w,strict=True):y[i]=v
    return y

class Policy(nn.Module):
    def __init__(self,h):
        super().__init__();self.b=nn.Linear(BOARD_FEATURES,h);self.m=nn.Linear(MOVE_FEATURES,h);self.interact=nn.Parameter(torch.ones(h));self.move_out=nn.Parameter(torch.zeros(h));self.bias=nn.Parameter(torch.zeros(()))
    def score(self,bx,mx):
        bh=torch.relu(self.b(bx));mh=torch.relu(self.m(mx));
        if bh.ndim==1:bh=bh.unsqueeze(0)
        return ((bh*mh)*self.interact).sum(-1)+(mh*self.move_out).sum(-1)+self.bias

def metrics(model,rows,split):
    model.eval();n=t1=t3=ov=0;mrr=0.
    with torch.no_grad():
        for s,fen,cs in rows:
            if s!=split:continue
            b=chess.Board(fen);legal=list(b.legal_moves);bx=torch.from_numpy(board_features(b));mx=torch.from_numpy(np.stack([move_features(b,m) for m in legal]));order=torch.argsort(model.score(bx,mx),descending=True).tolist();best=cs[0][0];rank=next(i for i,j in enumerate(order) if legal[j].uci()==best);pred={legal[j].uci() for j in order[:3]};teach={m for m,_ in cs[:3]};n+=1;t1+=rank==0;t3+=rank<3;mrr+=1/(rank+1);ov+=len(pred&teach)
    return {'records':n,'top1':t1/max(1,n),'top3':t3/max(1,n),'mrr':mrr/max(1,n),'mean_teacher_top3_overlap':ov/max(1,n)}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--teacher',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--hidden',type=int,required=True);ap.add_argument('--epochs',type=int,default=10);ap.add_argument('--seed',type=int,default=20260908);a=ap.parse_args();torch.manual_seed(a.seed);np.random.seed(a.seed);torch.set_num_threads(1);rows=load_rows(a.teacher);train=[r for r in rows if r[0]=='train'];model=Policy(a.hidden);opt=torch.optim.AdamW(model.parameters(),lr=2e-3,weight_decay=1e-5);rng=np.random.default_rng(a.seed+a.hidden)
    for ep in range(1,a.epochs+1):
        rng.shuffle(train);model.train();loss_sum=0.
        for _,fen,cs in train:
            b=chess.Board(fen);legal=list(b.legal_moves);uci=[m.uci() for m in legal];bx=torch.from_numpy(board_features(b));mx=torch.from_numpy(np.stack([move_features(b,m) for m in legal]));logits=model.score(bx,mx);y=target(uci,cs);loss=-(y*torch.log_softmax(logits,0)).sum();opt.zero_grad();loss.backward();opt.step();loss_sum+=float(loss)
        print(json.dumps({'epoch':ep,'loss':loss_sum/max(1,len(train)),'validation':metrics(model,rows,'validation')}),flush=True)
    a.output.parent.mkdir(parents=True,exist_ok=True);torch.jit.script(model.eval()).save(str(a.output));meta={'hidden':a.hidden,'records':len(rows),'metrics':{s:metrics(model,rows,s) for s in ('train','validation','holdout')}};a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2)+'\n');print('FINAL',json.dumps(meta));
if __name__=='__main__':main()
