import os,sys,json,subprocess,time,random,numpy as np
sys.path.insert(0, sys.argv[2])
from experiments.numba_core import generate_legal_moves, make_move_inplace, in_check
from experiments.numba_search import position_key, _next_halfmove_clock
PIECE={'P':1,'N':2,'B':3,'R':4,'Q':5,'K':6,'p':-1,'n':-2,'b':-3,'r':-4,'q':-5,'k':-6}
def parse(fen):
 p=fen.split();b=np.zeros(64,dtype=np.int8)
 for rr,s in enumerate(p[0].split('/')):
  rank=7-rr;f=0
  for ch in s:
   if ch.isdigit():f+=int(ch)
   else:b[rank*8+f]=PIECE[ch];f+=1
 side=1 if p[1]=='w' else -1
 c=(1 if 'K'in p[2] else 0)|(2 if 'Q'in p[2] else 0)|(4 if 'k'in p[2] else 0)|(8 if 'q'in p[2] else 0)
 ep=-1 if p[3]=='-' else ord(p[3][0])-97+(int(p[3][1])-1)*8
 return b,side,c,ep,int(p[4])
class W:
 def __init__(self,d):
  env=os.environ.copy();env['PYTHONPATH']=d;env['PYTHONWARNINGS']='ignore'
  self.p=subprocess.Popen([sys.executable,os.path.join(os.path.dirname(__file__),'v13_v12_arena_worker.py')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,env=env)
 def go(self,b,s,c,e,hm,hist,nodes):
  self.p.stdin.write(json.dumps({'board':b.tolist(),'side':s,'castling':c,'ep':e,'halfmove':hm,'history':[int(x) for x in hist],'nodes':nodes})+'\n');self.p.stdin.flush()
  line=self.p.stdout.readline()
  if not line: raise RuntimeError('worker died: '+self.p.stderr.read()[-2000:])
  r=json.loads(line)
  if 'error'in r:raise RuntimeError(r['error'])
  return r
 def close(self):
  self.p.terminate();self.p.wait(timeout=5)
def dead(b):
 pcs=[abs(int(x)) for x in b if int(x)!=0 and abs(int(x))!=6]
 return len(pcs)==0 or (len(pcs)==1 and pcs[0] in(2,3))
def game(cand,base,root,cand_side,nodes,maxplies):
 b,s,c,e,hm=parse(root);hist=[];seen={int(position_key(b,s,c,e)):1}
 for ply in range(maxplies):
  legal,n=generate_legal_moves(b,s,c,e);legal=legal[:n]
  if n==0:return (-s*cand_side if in_check(b,s) else 0,'mate' if in_check(b,s) else 'stalemate',ply)
  if hm>=100 or dead(b):return (0,'rule-draw',ply)
  w=cand if s==cand_side else base
  keep=min(hm,len(hist));hh=hist[-keep:] if keep else []
  r=w.go(b,s,c,e,hm,hh,nodes);m=int(r['move'])
  if m not in set(int(x) for x in legal):raise RuntimeError(('illegal',m))
  hist.append(int(position_key(b,s,c,e)));hm=_next_halfmove_clock(b,m,hm)
  c,e,_,_=make_move_inplace(b,s,c,e,m);s=-s
  k=int(position_key(b,s,c,e));seen[k]=seen.get(k,0)+1
  if seen[k]>=3:return (0,'repetition',ply+1)
 return(0,'maxply',maxplies)
def load_roots(path,start,pairs,seed):
 lines=[]
 with open(path,encoding='utf-8') as f:
  for i,line in enumerate(f):
   x=line.strip()
   if x and not x.startswith('#'):lines.append((f'uho-{i:03d}',x))
 if start<0 or start+pairs>len(lines):raise ValueError((start,pairs,len(lines)))
 roots=lines[start:start+pairs]
 random.Random(seed).shuffle(roots)
 return roots
def main():
 cand_dir,base_dir=sys.argv[1],sys.argv[2];nodes=int(sys.argv[3]);pairs=int(sys.argv[4]);seed=int(sys.argv[5]);maxplies=int(sys.argv[6]);epd=sys.argv[7];start=int(sys.argv[8])
 roots=load_roots(epd,start,pairs,seed)
 cand=W(cand_dir);base=W(base_dir)
 b,s,c,e,hm=parse(roots[0][1]);print('compiling candidate...',flush=True);t=time.time();cand.go(b,s,c,e,hm,[],1000);print('cand ready',round(time.time()-t,2),flush=True)
 print('compiling base...',flush=True);t=time.time();base.go(b,s,c,e,hm,[],1000);print('base ready',round(time.time()-t,2),flush=True)
 rec=[]
 try:
  for i,(name,fen) in enumerate(roots):
   for cs in (1,-1):
    t=time.time();res,why,plies=game(cand,base,fen,cs,nodes,maxplies);rec.append(res)
    print(i,name,'cand',('W'if cs==1 else'B'),'res',res,why,'plies',plies,'wall',round(time.time()-t,2),'score',sum((x+1)/2 for x in rec),'/',len(rec),flush=True)
 finally:cand.close();base.close()
 print('FINAL',sum((x+1)/2 for x in rec),'/',len(rec),'WDL',rec.count(1),rec.count(0),rec.count(-1),flush=True)
if __name__=='__main__':main()
