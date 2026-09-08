#!/usr/bin/env python3
"""Reusable paired fixed-node arena for packaged Python engine experiments."""
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
        board=chess.Board(fen); encoded=encode_position(board)
        return int(position_key(encoded.board,encoded.side,encoded.castling,encoded.ep_square))
    for line in sys.stdin:
        query=json.loads(line); board=chess.Board(query['fen']); encoded=encode_position(board); prior=query.get('prior',[])
        keep=min(board.halfmove_clock,len(prior))
        history=np.asarray([key_for_fen(fen) for fen in prior[-keep:]],dtype=np.uint64) if keep else np.empty(0,dtype=np.uint64)
        out=iterative_search_stateful(encoded.board,encoded.side,encoded.castling,encoded.ep_square,board.halfmove_clock,history,len(history),int(query['nodes']))
        print(json.dumps({'uci':move_to_uci(int(out[0])),'score':int(out[1]),'depth':int(out[2]),'nodes':int(out[3])}),flush=True)
    return 0


class Worker:
    def __init__(self, script: Path, engine_dir: Path) -> None:
        self.proc=subprocess.Popen([sys.executable,str(script),'--worker',str(engine_dir)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        assert self.proc.stdin and self.proc.stdout
        self.stdin: TextIO=self.proc.stdin; self.stdout: TextIO=self.proc.stdout
    def search(self, board: chess.Board, prior: list[str], nodes: int) -> dict[str,object]:
        self.stdin.write(json.dumps({'fen':board.fen(),'prior':prior,'nodes':nodes})+'\n'); self.stdin.flush(); line=self.stdout.readline()
        if not line: raise RuntimeError(f'engine worker exited with {self.proc.poll()}')
        result=json.loads(line); move=chess.Move.from_uci(str(result['uci']))
        if move not in board.legal_moves: raise RuntimeError(f'illegal worker move {move} in {board.fen()}')
        result['move']=move; return result
    def close(self) -> None:
        if self.proc.poll() is None: self.proc.terminate()
        self.proc.wait(timeout=5)


def parse_args() -> argparse.Namespace:
    parser=argparse.ArgumentParser(); parser.add_argument('candidate',type=Path,nargs='?'); parser.add_argument('control',type=Path,nargs='?')
    parser.add_argument('--nodes',type=int,default=16000); parser.add_argument('--pairs',type=int,default=32); parser.add_argument('--opening-file',type=Path)
    parser.add_argument('--opening-offset',type=int,default=0); parser.add_argument('--max-plies',type=int,default=220); parser.add_argument('--json-out',type=Path)
    parser.add_argument('--worker',type=Path,help=argparse.SUPPRESS); return parser.parse_args()


def load_openings(path: Path, offset: int, pairs: int) -> list[str]:
    rows=[line.strip() for line in path.read_text().splitlines() if line.strip() and not line.startswith('#')]; out=rows[offset:offset+pairs]
    if len(out)!=pairs: raise SystemExit('insufficient openings')
    for fen in out: chess.Board(fen)
    return out


def play_game(candidate: Worker, control: Worker, fen: str, candidate_white: bool, nodes: int, max_plies: int) -> tuple[float,str,int]:
    board=chess.Board(fen); prior=[]
    for _ in range(max_plies):
        outcome=board.outcome(claim_draw=True)
        if outcome is not None: return (0.5 if outcome.winner is None else float(outcome.winner==candidate_white),board.result(claim_draw=True),board.ply())
        engine=candidate if board.turn==candidate_white else control; result=engine.search(board,prior,nodes); prior.append(board.fen()); board.push(result['move'])
    return 0.5,'max-ply-draw',board.ply()


def controller_main(args: argparse.Namespace) -> int:
    if args.candidate is None or args.control is None or args.opening_file is None: raise SystemExit('candidate, control and --opening-file required')
    script=Path(__file__).resolve(); openings=load_openings(args.opening_file,args.opening_offset,args.pairs)
    candidate=Worker(script,args.candidate.resolve()); control=Worker(script,args.control.resolve()); rows=[]
    try:
        candidate.search(chess.Board(openings[0]),[],min(300,args.nodes)); control.search(chess.Board(openings[0]),[],min(300,args.nodes))
        for index,fen in enumerate(openings,start=args.opening_offset):
            for candidate_white in (True,False):
                score,result,plies=play_game(candidate,control,fen,candidate_white,args.nodes,args.max_plies)
                row={'opening':index,'candidate_white':candidate_white,'candidate_score':score,'result':result,'plies':plies}; rows.append(row); print(json.dumps(row,sort_keys=True),flush=True)
    finally:
        candidate.close(); control.close()
    total=sum(float(row['candidate_score']) for row in rows); games=len(rows); fraction=total/games
    elo=400*math.log10(fraction/(1-fraction)) if 0<fraction<1 else None
    out={'nodes_per_move':args.nodes,'opening_file':str(args.opening_file),'opening_offset':args.opening_offset,'opening_pairs':args.pairs,'games':games,'score':total,'score_fraction':fraction,'naive_elo_from_score':elo,'max_plies':args.max_plies,'games_detail':rows}
    print('FINAL '+json.dumps({key:value for key,value in out.items() if key!='games_detail'},sort_keys=True))
    if args.json_out:
        args.json_out.parent.mkdir(parents=True,exist_ok=True); args.json_out.write_text(json.dumps(out,indent=2,sort_keys=True)+'\n')
    return 0


def main() -> int:
    args=parse_args(); return worker_main(args.worker.resolve()) if args.worker is not None else controller_main(args)


if __name__=='__main__': raise SystemExit(main())
