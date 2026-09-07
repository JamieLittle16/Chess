import json,sys,numpy as np
from experiments.numba_search import iterative_search_stateful
for line in sys.stdin:
    try:
        q=json.loads(line)
        b=np.asarray(q['board'],dtype=np.int8)
        h=np.asarray(q.get('history',[]),dtype=np.uint64)
        out=iterative_search_stateful(b,int(q['side']),int(q['castling']),int(q['ep']),int(q['halfmove']),h,len(h),int(q['nodes']))
        print(json.dumps({'move':int(out[0]),'score':int(out[1]),'depth':int(out[2]),'nodes':int(out[3])}),flush=True)
    except Exception as e:
        print(json.dumps({'error':repr(e)}),flush=True)
