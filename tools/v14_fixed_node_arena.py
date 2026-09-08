#!/usr/bin/env python3
"""Reusable paired fixed-node arena for Python V14 experiments."""
from __future__ import annotations
import argparse, json, math, subprocess, sys
from pathlib import Path
from typing import TextIO
import chess

def worker_main(engine_dir: Path) -> int:
    sys.path.insert(0, str(engine_dir)); import numpy as np
    from experiments.numba_core import encode_position, move_to_uci
    from experiments.numba_search import iterative_search_stateful, position_key
    def key_for_fen(fen: str) -> int:
        b=chess.Board(fen); e=encode_position(b); return int(position_key(e.board,e.side,e.castling,e.ep_square))
    for line in sys.stdin:
        q=json.loads(line); b=chess.Board(q['fen']); e=encode_position(b); prior=q.get('prior',[]); keep=min(b.halfmove_clock,len(prior))
        history=np.asarray([key_for_fen(f) for f in prior[-keep:]],dtype=np.uint64) if keep else np.empty(0,dtype=np.uint64)
        o=iterative_search_stateful(e.board,e.side,e.castling,e.ep_square,b.halfmove_clock,history,len(history),int(q['nodes']))
        print(json.dumps({'uci':move_to_uci(int(o[0])),'score':int(o[1]),'depth':int(o[2]),'nodes':int(o[3])}),flush=True)
    return 0
class Worker:
    def __init__(self,script:Path,engine_dir:Path)->None:
        self.proc=subprocess.Popen([sys.executable,str(script),'--worker',str(engine_dir)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1);assert self.proc.stdin and self.proc.stdout;self.stdin:TextIO=self.proc.stdin;self.stdout:TextIO=self.proc.stdout
    def search(self,b:chess.Board,prior:list[str],nodes:int)->dict[str,object]:
        self.stdin.write(json.dumps({'fen':b.fen(),'prior':prior,'nodes':nodes})+'\n');self.stdin.flush();line=self.stdout.readline()
        if not line:raise RuntimeError(f'worker exited {self.proc.poll()}')
        r=json.loads(line);m=chess.Move.from_uci(str(r['uci']));
        if m not in b.legal_moves:raise RuntimeError(f'illegal {m}')
        r['move']=m;return r
    def close(self):
        if self.proc.poll() is None:self.proc.terminate()
        self.proc.wait(timeout=5)
def main():
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path,nargs='?');p.add_argument('control',type=Path,nargs='?');p.add_argument('--nodes',type=int,default=16000);p.add_argument('--pairs',type=int,default=32);p.add_argument('--opening-file',type=Path);p.add_argument('--max-plies',type=int,default=220);p.add_argument('--json-out',type=Path);p.add_argument('--worker',type=Path,help=argparse.SUPPRESS);a=p.parse_args()
    if a.worker is not None:return worker_main(a.worker.resolve())
    opens=[x.strip() for x in a.opening_file.read_text().splitlines() if x.strip()][:a.pairs];assert len(opens)==a.pairs
    c=Worker(Path(__file__).resolve(),a.candidate.resolve());bse=Worker(Path(__file__).resolve(),a.control.resolve());rows=[]
    try:
        c.search(chess.Board(opens[0]),[],min(300,a.nodes));bse.search(chess.Board(opens[0]),[],min(300,a.nodes))
        for i,fen in enumerate(opens):
            for cw in (True,False):
                b=chess.Board(fen);prior=[];score=.5;res='max-ply-draw'
                for _ in range(a.max_plies):
                    o=b.outcome(claim_draw=True)
                    if o is not None:score=.5 if o.winner is None else float(o.winner==cw);res=b.result(claim_draw=True);break
                    eng=c if b.turn==cw else bse;r=eng.search(b,prior,a.nodes);prior.append(b.fen());b.push(r['move'])
                rows.append({'opening':i,'candidate_white':cw,'candidate_score':score,'result':res});print(rows[-1],flush=True)
    finally:c.close();bse.close()
    total=sum(r['candidate_score'] for r in rows);games=len(rows);f=total/games;elo=400*math.log10(f/(1-f)) if 0<f<1 else None;out={'games':games,'score':total,'score_fraction':f,'naive_elo_from_score':elo,'rows':rows};print('FINAL '+json.dumps({k:v for k,v in out.items() if k!='rows'}))
    if a.json_out:a.json_out.write_text(json.dumps(out,indent=2)+'\n')
    return 0
if __name__=='__main__':raise SystemExit(main())
