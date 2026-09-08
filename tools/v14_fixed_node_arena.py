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
        self.proc=subprocess.Popen([sys.executable,str(script),'--worker',str(engine_dir)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1); assert self.proc.stdin and self.proc.stdout; self.stdin:TextIO=self.proc.stdin; self.stdout:TextIO=self.proc.stdout
    def search(self,b:chess.Board,prior:list[str],nodes:int)->dict[str,object]:
        self.stdin.write(json.dumps({'fen':b.fen(),'prior':prior,'nodes':nodes})+'\n'); self.stdin.flush(); line=self.stdout.readline()
        if not line: raise RuntimeError(f'engine worker exited with {self.proc.poll()}')
        r=json.loads(line); m=chess.Move.from_uci(str(r['uci']))
        if m not in b.legal_moves: raise RuntimeError(f'illegal worker move {m} in {b.fen()}')
        r['move']=m; return r
    def close(self)->None:
        if self.proc.poll() is None:self.proc.terminate()
        self.proc.wait(timeout=5)

def parse_args()->argparse.Namespace:
    p=argparse.ArgumentParser();p.add_argument('candidate',type=Path,nargs='?');p.add_argument('control',type=Path,nargs='?');p.add_argument('--nodes',type=int,default=16000);p.add_argument('--pairs',type=int,default=32);p.add_argument('--opening-file',type=Path);p.add_argument('--opening-offset',type=int,default=0);p.add_argument('--max-plies',type=int,default=220);p.add_argument('--json-out',type=Path);p.add_argument('--worker',type=Path,help=argparse.SUPPRESS);return p.parse_args()
def load_openings(path:Path,offset:int,pairs:int)->list[str]:
    rows=[x.strip() for x in path.read_text().splitlines() if x.strip() and not x.startswith('#')]; out=rows[offset:offset+pairs]
    if len(out)!=pairs: raise SystemExit('insufficient openings')
    for f in out:chess.Board(f)
    return out
def play_game(c:Worker,bse:Worker,fen:str,cw:bool,nodes:int,max_plies:int)->tuple[float,str,int]:
    b=chess.Board(fen); prior=[]
    for _ in range(max_plies):
        o=b.outcome(claim_draw=True)
        if o is not None:return (0.5 if o.winner is None else float(o.winner==cw),b.result(claim_draw=True),b.ply())
        e=c if b.turn==cw else bse;r=e.search(b,prior,nodes);prior.append(b.fen());b.push(r['move'])
    return 0.5,'max-ply-draw',b.ply()
def controller_main(a:argparse.Namespace)->int:
    if a.candidate is None or a.control is None or a.opening_file is None:raise SystemExit('candidate, control and --opening-file required')
    script=Path(__file__).resolve(); opens=load_openings(a.opening_file,a.opening_offset,a.pairs);c=Worker(script,a.candidate.resolve());b=Worker(script,a.control.resolve());rows=[]
    try:
        c.search(chess.Board(opens[0]),[],min(300,a.nodes));b.search(chess.Board(opens[0]),[],min(300,a.nodes))
        for i,fen in enumerate(opens,start=a.opening_offset):
            for cw in (True,False):
                score,result,plies=play_game(c,b,fen,cw,a.nodes,a.max_plies);row={'opening':i,'candidate_white':cw,'candidate_score':score,'result':result,'plies':plies};rows.append(row);print(json.dumps(row,sort_keys=True),flush=True)
    finally:c.close();b.close()
    total=sum(float(r['candidate_score']) for r in rows);games=len(rows);f=total/games;elo=400*math.log10(f/(1-f)) if 0<f<1 else None
    out={'nodes_per_move':a.nodes,'opening_file':str(a.opening_file),'opening_offset':a.opening_offset,'opening_pairs':a.pairs,'games':games,'score':total,'score_fraction':f,'naive_elo_from_score':elo,'max_plies':a.max_plies,'games_detail':rows};print('FINAL '+json.dumps({k:v for k,v in out.items() if k!='games_detail'},sort_keys=True))
    if a.json_out:a.json_out.parent.mkdir(parents=True,exist_ok=True);a.json_out.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    return 0
def main()->int:
    a=parse_args();return worker_main(a.worker.resolve()) if a.worker is not None else controller_main(a)
if __name__=='__main__':raise SystemExit(main())
