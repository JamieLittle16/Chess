#!/usr/bin/env python3
"""Build a compact two-colour opening repertoire from an offline Stockfish teacher.

For the repertoire side, keep the single best teacher move. On opponent turns, branch over the top
N teacher moves so the shipped book remains useful after several plausible deviations. The output is
plain JSON data; no engine is used at runtime.
"""
from __future__ import annotations
import argparse,json
from pathlib import Path
import chess,chess.engine


def key(board:chess.Board)->str:
    return ' '.join(board.fen(en_passant='fen').split()[:4])


def main()->int:
    ap=argparse.ArgumentParser();ap.add_argument('--stockfish',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);ap.add_argument('--plies',type=int,default=14);ap.add_argument('--opponent-width',type=int,default=3);ap.add_argument('--nodes',type=int,default=25000);a=ap.parse_args()
    book:dict[str,str]={};stats={}
    engine=chess.engine.SimpleEngine.popen_uci(str(a.stockfish))
    engine.configure({'Threads':1,'Hash':64})
    try:
        for repertoire_color in (chess.WHITE,chess.BLACK):
            seen:set[tuple[str,int,bool]]=set(); analysed=0
            def visit(board:chess.Board,ply:int)->None:
                nonlocal analysed
                if ply>=a.plies or board.is_game_over(claim_draw=False):return
                state=(key(board),ply,repertoire_color); 
                if state in seen:return
                seen.add(state)
                width=1 if board.turn==repertoire_color else a.opponent_width
                infos=engine.analyse(board,chess.engine.Limit(nodes=a.nodes),multipv=width)
                analysed+=1
                if isinstance(infos,dict):infos=[infos]
                moves=[]
                for info in infos:
                    pv=info.get('pv',[])
                    if pv and pv[0] in board.legal_moves and pv[0] not in moves:moves.append(pv[0])
                if not moves:return
                if board.turn==repertoire_color:
                    book[key(board)]=moves[0].uci(); moves=moves[:1]
                for mv in moves:
                    child=board.copy(stack=False);child.push(mv);visit(child,ply+1)
            visit(chess.Board(),0)
            stats['white' if repertoire_color else 'black']={'states':len(seen),'analyses':analysed}
    finally:engine.quit()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    payload={'schema':1,'plies':a.plies,'opponent_width':a.opponent_width,'nodes':a.nodes,'entries':dict(sorted(book.items())),'stats':stats}
    a.output.write_text(json.dumps(payload,separators=(',',':'),sort_keys=True)+'\n')
    print(json.dumps({'entries':len(book),'stats':stats,'bytes':a.output.stat().st_size},sort_keys=True))
    return 0
if __name__=='__main__':raise SystemExit(main())
