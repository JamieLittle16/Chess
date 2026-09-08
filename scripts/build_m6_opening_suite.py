#!/usr/bin/env python3
"""Derive the large M6 SPRT opening suite from the pinned Stockfish CC0 UHO book."""
from __future__ import annotations
import argparse, base64, hashlib, heapq, json, sys, zipfile
from dataclasses import dataclass
from pathlib import Path
SOURCE_REPOSITORY="official-stockfish/books"
SOURCE_COMMIT="65815ccdbc7727cd4f6aee252ba8f67fb740e92f"
SOURCE_ARCHIVE="UHO_Lichess_4852_v1.epd.zip"
SOURCE_MEMBER="UHO_Lichess_4852_v1.epd"
SOURCE_GIT_BLOB_SHA="e439636101786177ece850d3607356891c1cc2cd"
SOURCE_ARCHIVE_SIZE=42_877_788
SOURCE_ARCHIVE_SHA256="4e298f11e8acfa106babe02968f2e61582145e7874c59284690b20b9650e0e07"
SOURCE_TOTAL_POSITIONS=2_632_036
SOURCE_SRI_SHA384_BASE64="QHAU1P3LurcJr7UTRI7HZCVFsoYBWC3OTsBqZY/FfQA6VQo3MmECWtByB4gVACW5"
SOURCE_LICENSE="CC0-1.0"
SUITE_ID="m6-uho-lichess-5000-v1"
SELECTION_SEED="Chess/m6-uho-lichess-5000-v1"
SELECTION_COUNT=5_000
SUITE_SHA256="5445819229270140036023a507c41edffc9307ac2cca1ca2efd20e1ddb8d670e"
class DerivationError(ValueError): pass
@dataclass(frozen=True)
class SelectedPosition:
    rank_sha256:str; source_line:int; epd:str
def select_positions(source):
    sri=hashlib.sha384(); heap=[]; count=0; seed=SELECTION_SEED.encode('ascii')+b'\0'
    for source_line,raw in enumerate(source,start=1):
        normalized=raw.replace(b'\r\n',b'\n').replace(b'\r',b'\n'); sri.update(normalized); line=normalized.rstrip(b'\n')
        if not line: continue
        count+=1; digest=hashlib.sha256(seed+line).digest(); score=int.from_bytes(digest,'big'); entry=(-score,source_line,digest,line)
        if len(heap)<SELECTION_COUNT: heapq.heappush(heap,entry)
        elif -score>heap[0][0]: heapq.heapreplace(heap,entry)
    selected=[SelectedPosition(d.hex(),sl,line.decode('utf-8')) for _,sl,d,line in heap]; selected.sort(key=lambda x:(x.rank_sha256,x.epd))
    return selected,base64.b64encode(sri.digest()).decode('ascii'),count
def sha256_file(path):
    d=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): d.update(chunk)
    return d.hexdigest()
def derive(archive,output_dir):
    archive=archive.expanduser().resolve(strict=True)
    if archive.stat().st_size!=SOURCE_ARCHIVE_SIZE: raise DerivationError('source archive size mismatch')
    if sha256_file(archive)!=SOURCE_ARCHIVE_SHA256: raise DerivationError('source archive SHA-256 mismatch')
    try:
        with zipfile.ZipFile(archive) as z:
            if z.namelist()!=[SOURCE_MEMBER]: raise DerivationError('source archive members mismatch')
            with z.open(SOURCE_MEMBER) as source: selected,sri,total=select_positions(source)
    except zipfile.BadZipFile as exc: raise DerivationError(f'invalid source ZIP: {exc}') from exc
    if sri!=SOURCE_SRI_SHA384_BASE64: raise DerivationError('source SRI mismatch')
    if total!=SOURCE_TOTAL_POSITIONS: raise DerivationError(f'source position count mismatch: {total}')
    if len(selected)!=SELECTION_COUNT or len({x.epd for x in selected})!=SELECTION_COUNT: raise DerivationError('derived suite size/uniqueness mismatch')
    output_dir.mkdir(parents=True,exist_ok=True); epd=output_dir/f'{SUITE_ID}.epd'; meta=output_dir/f'{SUITE_ID}.json'
    data=('\n'.join(x.epd for x in selected)+'\n').encode(); digest=hashlib.sha256(data).hexdigest()
    if digest!=SUITE_SHA256: raise DerivationError(f'suite SHA mismatch: {digest}')
    epd.write_bytes(data)
    meta.write_text(json.dumps({'schema_version':1,'suite_id':SUITE_ID,'positions':SELECTION_COUNT,'sha256':digest,'source':{'repository':SOURCE_REPOSITORY,'commit':SOURCE_COMMIT,'archive':SOURCE_ARCHIVE,'license':SOURCE_LICENSE}},indent=2,sort_keys=True)+'\n')
    return epd,meta,digest
def main():
    p=argparse.ArgumentParser(); p.add_argument('--archive',type=Path,required=True); p.add_argument('--output-dir',type=Path,required=True); a=p.parse_args()
    try: epd,meta,digest=derive(a.archive,a.output_dir)
    except (OSError,UnicodeDecodeError,DerivationError) as exc: print(f'M6 opening-suite derivation: {exc}',file=sys.stderr); return 2
    print(epd); print(meta); print(f'sha256={digest}'); return 0
if __name__=='__main__': raise SystemExit(main())
