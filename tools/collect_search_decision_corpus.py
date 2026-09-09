#!/usr/bin/env python3
"""Collect leakage-safe alpha/beta static-evaluation decisions from traced Rust search."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
import subprocess
import sys


def sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''): h.update(block)
    return h.hexdigest()


def group_name(index:int,fen:str)->str:
    return f"uho-{index:04d}-{hashlib.sha256(fen.encode()).hexdigest()[:12]}"


def run_root(engine:Path,raw:Path,group:str,fen:str,nodes:int,stride:int)->None:
    env=os.environ.copy()
    env['CHESS_SEARCH_DECISION_TRACE_FILE']=str(raw)
    env['CHESS_SEARCH_DECISION_TRACE_GROUP']=group
    env['CHESS_SEARCH_DECISION_TRACE_STRIDE']=str(stride)
    p=subprocess.Popen([str(engine)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1,env=env)
    assert p.stdin is not None and p.stdout is not None
    transcript=[]
    try:
        p.stdin.write('uci\nisready\nucinewgame\n'+f'position fen {fen}\n'+f'go nodes {nodes}\n');p.stdin.flush()
        saw=False
        for line in p.stdout:
            transcript.append(line)
            if line.startswith('bestmove '): saw=True;break
        if not saw: raise RuntimeError(f'engine exited before bestmove for {group}')
        p.stdin.write('quit\n');p.stdin.flush();p.stdin.close();p.wait(timeout=60)
    except BaseException:
        p.kill();p.wait(timeout=10);raise
    out=''.join(transcript)
    if p.returncode != 0 or 'uciok' not in out or 'readyok' not in out:
        raise RuntimeError(f'trace engine failed for {group}: {out[-2000:]}')


def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--engine',type=Path,required=True);ap.add_argument('--openings',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);ap.add_argument('--manifest',type=Path,required=True)
    ap.add_argument('--roots',type=int,default=64);ap.add_argument('--nodes',type=int,default=20000)
    ap.add_argument('--stride',type=int,default=4);ap.add_argument('--duplicate-cap',type=int,default=2)
    a=ap.parse_args()
    if min(a.roots,a.nodes,a.stride,a.duplicate_cap)<=0: raise ValueError('numeric arguments must be positive')
    engine=a.engine.resolve(); openings=a.openings.resolve()
    roots=[x.strip() for x in openings.read_text().splitlines() if x.strip() and not x.lstrip().startswith('#')][:a.roots]
    if len(roots)!=a.roots: raise ValueError('not enough roots')
    raw=a.output.with_suffix(a.output.suffix+'.raw');raw.parent.mkdir(parents=True,exist_ok=True);raw.unlink(missing_ok=True)
    groups=[group_name(i,fen) for i,fen in enumerate(roots)]
    for i,(g,fen) in enumerate(zip(groups,roots,strict=True)):
        run_root(engine,raw,g,fen,a.nodes,a.stride)
        if (i+1)%8==0: print(json.dumps({'roots_done':i+1}),flush=True)

    allowed=set(groups);counts=Counter();kept=Counter();dup=Counter();rows=[];per_key=defaultdict(int)
    for lineno,line in enumerate(raw.read_text().splitlines(),1):
        if not line: continue
        parts=line.split('\t',8)
        if len(parts)!=9: raise ValueError(f'bad trace line {lineno}: fields={len(parts)}')
        group,kind,depth,ply,qply,alpha,beta,score,fen=parts
        if group not in allowed or kind not in {'rfp','qstable','qceil','qstand','qpath'}: raise ValueError(f'bad trace identity line {lineno}')
        if len(fen.split())!=6: raise ValueError(f'bad FEN line {lineno}')
        vals=tuple(map(int,(depth,ply,qply,alpha,beta,score)))
        counts[kind]+=1
        key=(group,kind,*vals,fen)
        per_key[key]+=1
        if per_key[key]>a.duplicate_cap:
            dup[kind]+=1;continue
        h=int.from_bytes(hashlib.sha256(group.encode()).digest()[:8],'big')%10
        split='holdout' if h==0 else ('validation' if h==1 else 'train')
        row={'split':split,'group':group,'kind':kind,'depth':vals[0],'ply':vals[1],'qply':vals[2],
             'alpha':vals[3],'beta':vals[4],'teacher_cp':vals[5],'fen':fen}
        rows.append(json.dumps(row,separators=(',',':')));kept[kind]+=1
    if len(rows)<5000: raise ValueError(f'too few retained records: {len(rows)}')
    a.output.write_text('\n'.join(rows)+'\n')
    split_counts=Counter(json.loads(x)['split'] for x in rows)
    manifest={'schema':'chess-search-decision-corpus-v1','root_count':len(roots),'nodes_per_root':a.nodes,
              'trace_stride':a.stride,'duplicate_cap':a.duplicate_cap,'raw_events':dict(counts),
              'retained_events':dict(kept),'duplicates_dropped':dict(dup),'records':len(rows),
              'split_counts':dict(split_counts),'engine_sha256':sha256_file(engine),
              'opening_sha256':sha256_file(openings),'corpus_sha256':sha256_file(a.output)}
    a.manifest.write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n');print('FINAL',json.dumps(manifest,sort_keys=True),flush=True)
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (OSError,RuntimeError,ValueError,subprocess.SubprocessError) as e:
        print(f'decision corpus collection failed: {e}',file=sys.stderr);raise SystemExit(1) from e
