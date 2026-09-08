#!/usr/bin/env python3
"""Label grouped V14 self-play positions with the Rust Gestalt static evaluator.

The Rust oracle reports side-to-move centipawns. Splits are assigned by immutable opening group,
so trajectories from the same opening can never leak across train/validation/holdout.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def split_for(group: str, salt: str, validation_permille: int, holdout_permille: int) -> str:
    digest = hashlib.sha256((salt + "\0" + group).encode()).digest()
    bucket = int.from_bytes(digest[:8], "little") % 1000
    if bucket < validation_permille:
        return "validation"
    if bucket < validation_permille + holdout_permille:
        return "holdout"
    return "train"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--positions", type=Path, required=True)
    ap.add_argument("--oracle", type=Path, required=True)
    ap.add_argument("--network", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--split-salt", default="Chess/v15-gestalt-h64")
    ap.add_argument("--validation-permille", type=int, default=100)
    ap.add_argument("--holdout-permille", type=int, default=100)
    args = ap.parse_args()

    payload = json.loads(args.positions.read_text())
    records = payload.get("records", [])
    if not records:
        raise SystemExit("positions corpus is empty")
    proc = subprocess.Popen(
        [str(args.oracle.resolve()), str(args.network.resolve())],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, bufsize=1,
    )
    assert proc.stdin is not None and proc.stdout is not None
    out_rows=[]
    counts={"train":0,"validation":0,"holdout":0}
    try:
        for index, record in enumerate(records):
            fen=str(record["fen"]); group=str(record["group"])
            proc.stdin.write(fen+"\n"); proc.stdin.flush()
            line=proc.stdout.readline()
            if not line:
                raise RuntimeError(f"Gestalt oracle closed at record {index}")
            cp=int(line.strip())
            split=split_for(group,args.split_salt,args.validation_permille,args.holdout_permille)
            counts[split]+=1
            out_rows.append({
                "schema_version":1,
                "group":group,
                "fen":fen,
                "split":split,
                "teacher_cp":cp,
                "teacher_mate":None,
                "teacher":"rust-gestalt-v13-b840-static",
            })
    finally:
        if proc.stdin is not None: proc.stdin.close()
        rc=proc.wait(timeout=30)
    if rc != 0:
        raise SystemExit(f"Gestalt oracle exited {rc}")
    if min(counts.values()) < 100:
        raise SystemExit(f"split too small: {counts}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(r,sort_keys=True)+"\n" for r in out_rows))
    print("FINAL",json.dumps({"records":len(out_rows),"split_counts":counts},sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
