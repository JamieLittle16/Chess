#!/usr/bin/env python3
"""Train a very cheap low-rank root policy from ranked Rust V15 candidate scores.

Runtime shape: sparse board features -> D ReLU lanes once per root; sparse move features -> D ReLU
lanes per legal move; score is their dot product plus a sparse linear move bias. This keeps the
teacher's board/move interaction while costing only O(D) work per active feature.
"""
from __future__ import annotations

import argparse,json,math
from pathlib import Path
import chess,numpy as np,torch
from torch import nn

PLANES=12; SQUARES=64; BOARD_FEATURES=PLANES*SQUARES+5
MOVE_FEATURES=64+64+6+6+5+4


def board_features(board:chess.Board)->np.ndarray:
    x=np.zeros(BOARD_FEATURES,dtype=np.float32)
    for sq,piece in board.piece_map().items():
        plane=(0 if piece.color else 6)+piece.piece_type-1;x[plane*64+sq]=1.0
    o=768;x[o]=1.0 if board.turn else -1.0
    x[o+1]=float(board.has_kingside_castling_rights(chess.WHITE));x[o+2]=float(board.has_queenside_castling_rights(chess.WHITE));x[o+3]=float(board.has_kingside_castling_rights(chess.BLACK));x[o+4]=float(board.has_queenside_castling_rights(chess.BLACK));return x


def move_features(board:chess.Board,move:chess.Move)->np.ndarray:
    x=np.zeros(MOVE_FEATURES,dtype=np.float32);o=0
    x[o+move.from_square]=1;o+=64;x[o+move.to_square]=1;o+=64
    p=board.piece_at(move.from_square)
    if p:x[o+p.piece_type-1]=1
    o+=6;c=board.piece_at(move.to_square)
    if board.is_en_passant(move):x[o]=1
    elif c:x[o+c.piece_type-1]=1
    o+=6
    if move.promotion:x[o+move.promotion-1]=1
    o+=5;x[o]=float(board.is_capture(move));x[o+1]=0.;x[o+2]=float(board.is_castling(move));x[o+3]=float(board.is_en_passant(move));return x


def load_rows(path:Path):
    rows=[]
    for line in path.read_text().splitlines():
        if not line.strip():continue
        r=json.loads(line)
        try:b=chess.Board(r['fen'])
        except ValueError:continue
        legal={m.uci() for m in b.legal_moves};cand=[(str(c['move']),int(c['score'])) for c in r.get('candidates',[]) if str(c['move']) in legal]
        if cand:
            cand.sort(key=lambda z:-z[1]);rows.append((str(r.get('split','train')),r['fen'],cand))
    return rows


def soft_target(legal,cand,temp=60.,max_gap=600.):
    y=torch.zeros(len(legal));best=cand[0][1];where={m:i for i,m in enumerate(legal)};ii=[];gg=[]
    for m,s in cand:
        if m in where:ii.append(where[m]);gg.append(max(-max_gap,float(s-best))/temp)
    w=torch.softmax(torch.tensor(gg),0)
    for i,v in zip(ii,w,strict=True):y[i]=v
    return y


class LowRank(nn.Module):
    def __init__(self,d:int):
        super().__init__();self.d=d;self.board=nn.Linear(BOARD_FEATURES,d);self.move=nn.Linear(MOVE_FEATURES,d);self.move_bias=nn.Linear(MOVE_FEATURES,1)
    def score(self,bx,mx):
        b=torch.relu(self.board(bx));m=torch.relu(self.move(mx))
        if b.ndim==1:b=b.unsqueeze(0)
        return ((m*b).sum(-1)/math.sqrt(self.d)+self.move_bias(mx).squeeze(-1))


def evaluate(model,rows,split):
    total=top1=top3=over=0;mrr=0.
    model.eval()
    with torch.no_grad():
        for s,fen,cand in rows:
            if s!=split:continue
            b=chess.Board(fen);legal=list(b.legal_moves);bx=torch.from_numpy(board_features(b));mx=torch.from_numpy(np.stack([move_features(b,m) for m in legal]));order=torch.argsort(model.score(bx,mx),descending=True).tolist();best=cand[0][0];rank=next(i for i,j in enumerate(order) if legal[j].uci()==best);pred3={legal[j].uci() for j in order[:3]};teach3={m for m,_ in cand[:3]};total+=1;top1+=rank==0;top3+=rank<3;mrr+=1/(rank+1);over+=len(pred3&teach3)
    return {'records':total,'top1':top1/max(1,total),'top3':top3/max(1,total),'mrr':mrr/max(1,total),'mean_teacher_top3_overlap':over/max(1,total)}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--teacher',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--dim',type=int,choices=(8,16,32),required=True);ap.add_argument('--epochs',type=int,default=12);ap.add_argument('--seed',type=int,default=20260908);a=ap.parse_args();torch.manual_seed(a.seed+a.dim);np.random.seed(a.seed+a.dim);torch.set_num_threads(1)
    rows=load_rows(a.teacher);train=[r for r in rows if r[0]=='train'];model=LowRank(a.dim);opt=torch.optim.AdamW(model.parameters(),lr=2e-3,weight_decay=1e-5);rng=np.random.default_rng(a.seed+a.dim);best=None;best_top1=-1.
    for ep in range(1,a.epochs+1):
        rng.shuffle(train);model.train();loss_sum=0.
        for _,fen,cand in train:
            b=chess.Board(fen);moves=list(b.legal_moves);legal=[m.uci() for m in moves];bx=torch.from_numpy(board_features(b));mx=torch.from_numpy(np.stack([move_features(b,m) for m in moves]));logits=model.score(bx,mx);target=soft_target(legal,cand);loss=-(target*torch.log_softmax(logits,0)).sum();opt.zero_grad();loss.backward();opt.step();loss_sum+=float(loss)
        val=evaluate(model,rows,'validation');print(json.dumps({'epoch':ep,'loss':loss_sum/max(1,len(train)),'validation':val}),flush=True)
        if val['top1']>best_top1:best_top1=val['top1'];best={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    assert best is not None;model.load_state_dict(best);metrics={s:evaluate(model,rows,s) for s in ('train','validation','holdout')};a.output.parent.mkdir(parents=True,exist_ok=True)
    st=model.state_dict();np.savez_compressed(a.output,board_w=st['board.weight'].numpy(),board_b=st['board.bias'].numpy(),move_w=st['move.weight'].numpy(),move_b=st['move.bias'].numpy(),linear_w=st['move_bias.weight'].numpy().reshape(-1),linear_b=st['move_bias.bias'].numpy())
    meta={'dimension':a.dim,'records':len(rows),'metrics':metrics,'board_features':BOARD_FEATURES,'move_features':MOVE_FEATURES};a.output.with_suffix('.json').write_text(json.dumps(meta,indent=2,sort_keys=True)+'\n');print('FINAL',json.dumps(meta,sort_keys=True));return 0
if __name__=='__main__':raise SystemExit(main())
