#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,math,queue,subprocess,sys,threading,time
from collections import Counter,deque
from pathlib import Path
import chess

class Agent:
    def __init__(self, root: str, runner: str):
        self.p=subprocess.Popen([sys.executable,runner,root],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        self.q=queue.Queue(); self.err=deque(maxlen=100)
        threading.Thread(target=self._out,daemon=True).start(); threading.Thread(target=self._err,daemon=True).start()
        assert json.loads(self._line(95)).get('ready') is True
    def _out(self):
        for x in self.p.stdout:self.q.put(x.rstrip('\n'))
        self.q.put(None)
    def _err(self):
        for x in self.p.stderr:self.err.append(x.rstrip('\n'))
    def _line(self,t):
        try:x=self.q.get(timeout=t)
        except queue.Empty as e:raise RuntimeError('timeout') from e
        if x is None:raise RuntimeError('closed '+'\n'.join(self.err))
        return x
    def reset(self):
        self.p.stdin.write('{"reset":true}\n'); self.p.stdin.flush(); assert json.loads(self._line(5)).get('reset') is True
    def move(self,b,ms,grace):
        self.p.stdin.write(json.dumps({'fen':b.fen(),'time_left_ms':max(0,int(ms))})+'\n'); self.p.stdin.flush()
        z=json.loads(self._line((max(0,ms)+grace)/1000)); m=chess.Move.from_uci(z['move']); assert m in b.legal_moves; return m
    def stop(self):
        if self.p.poll() is None:self.p.kill()
        self.p.wait(timeout=5)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--control',required=True); ap.add_argument('--candidate',required=True); ap.add_argument('--openings',required=True); ap.add_argument('--output',required=True); ap.add_argument('--label',required=True); ap.add_argument('--base-ms',type=int,default=2500); ap.add_argument('--inc-ms',type=int,default=50); ap.add_argument('--max-plies',type=int,default=180); ap.add_argument('--grace-ms',type=int,default=1200); ap.add_argument('--runner',default='tools/v14_agent_runner.py'); a=ap.parse_args()
    roots=[x.strip() for x in Path(a.openings).read_text().splitlines() if x.strip()]
    base=Agent(a.control,a.runner); cand=Agent(a.candidate,a.runner); rows=[]; pairs=[]
    def play(fen,cw):
        b=chess.Board(fen); cl={chess.WHITE:float(a.base_ms),chess.BLACK:float(a.base_ms)}; base.reset(); cand.reset(); tim=[]
        for _ in range(a.max_plies):
            o=b.outcome(claim_draw=True)
            if o is not None:return (0.5 if o.winner is None else float(o.winner==cw)),b.result(claim_draw=True),tim
            side=b.turn; use=side==cw; eng=cand if use else base; t=time.monotonic()
            try:m=eng.move(b,cl[side],a.grace_ms)
            except Exception as ex:return (0.0 if use else 1.0),f'engine-failure:{type(ex).__name__}',tim
            dt=(time.monotonic()-t)*1000; cl[side]-=dt
            if cl[side]<0:return (0.0 if use else 1.0),'flag',tim
            tim.append((use,dt)); b.push(m); cl[side]+=a.inc_ms
        return 0.5,'max-ply-draw',tim
    try:
        for i,fen in enumerate(roots):
            ps=0.0
            for cw in (True,False):
                s,r,t=play(fen,cw); ps+=s; rows.append({'opening':i,'candidate_white':cw,'score':s,'result':r,'candidate_ms':[x for c,x in t if c],'control_ms':[x for c,x in t if not c]}); print(i,cw,s,r,flush=True)
            pairs.append(ps)
    finally: base.stop(); cand.stop()
    score=sum(x['score'] for x in rows); n=len(rows); f=score/n; elo=400*math.log10(f/(1-f)) if 0<f<1 else None; ct=[v for x in rows for v in x['candidate_ms']]; bt=[v for x in rows for v in x['control_ms']]
    out={'candidate':a.label,'control':'exact packaged V14','games':n,'score':score,'score_fraction':f,'naive_elo_from_score':elo,'pair_histogram':dict(Counter(str(x) for x in pairs)),'candidate_mean_move_ms':sum(ct)/max(1,len(ct)),'control_mean_move_ms':sum(bt)/max(1,len(bt)),'details':rows}
    Path(a.output).write_text(json.dumps(out,indent=2)+'\n'); print('FINAL',json.dumps({k:v for k,v in out.items() if k!='details'}))
if __name__=='__main__': main()
