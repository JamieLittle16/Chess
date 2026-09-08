#!/usr/bin/env python3
"""Line-oriented harness for an unpacked Chessathon submission directory."""
from __future__ import annotations
import importlib,json,sys
from pathlib import Path
import numpy as np
if len(sys.argv)!=2: raise SystemExit("usage: v14_agent_runner.py SUBMISSION_DIR")
root=str(Path(sys.argv[1]).resolve());sys.path.insert(0,root);agent=importlib.import_module("agent")
def reset():
    agent._GAME_KEYS=[];agent._PENDING_AFTER_OUR_MOVE=None;agent._LAST_CALL_TIME_LEFT_MS=None;agent._LAST_GET_MOVE_ELAPSED_MS=None;agent._CLOCK_OVERHEAD_EMA_MS=40.0;agent._CLOCK_FEEDBACK_SAMPLES=0;agent._HASH_KEYS.fill(np.uint64(0));agent._HASH_MOVES.fill(np.int32(-1));agent._TT_TABLE.fill(np.uint64(0))
print(json.dumps({"ready":True}),flush=True)
for line in sys.stdin:
    try:
        request=json.loads(line)
        if request.get("reset"):
            reset();print(json.dumps({"reset":True}),flush=True);continue
        move=agent.get_move(request["fen"],int(request["time_left_ms"]));print(json.dumps({"move":move}),flush=True)
    except Exception as exc: print(json.dumps({"error":f"{type(exc).__name__}: {exc}"}),flush=True)
