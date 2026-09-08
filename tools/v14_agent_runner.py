from __future__ import annotations

import json
import os
import sys
from importlib import import_module

import numpy as np

protocol = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)
sys.path.insert(0, sys.argv[1])
agent = import_module("agent")


def reset_agent() -> None:
    required = (
        "_GAME_KEYS", "_PENDING_AFTER_OUR_MOVE", "_LAST_CALL_TIME_LEFT_MS",
        "_LAST_GET_MOVE_ELAPSED_MS", "_CLOCK_OVERHEAD_EMA_MS", "_CLOCK_FEEDBACK_SAMPLES",
        "_HASH_KEYS", "_HASH_MOVES", "_TT_TABLE",
    )
    missing = [name for name in required if not hasattr(agent, name)]
    if missing:
        raise RuntimeError(f"agent reset contract drifted; missing {missing}")
    agent._GAME_KEYS = []
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(np.uint64(0))
    agent._HASH_MOVES.fill(np.int32(-1))
    agent._TT_TABLE.fill(np.uint64(0))


protocol.write(json.dumps({"ready": True}) + "\n")
protocol.flush()
for line in sys.stdin:
    request = json.loads(line)
    if request.get("reset") is True:
        reset_agent()
        protocol.write(json.dumps({"reset": True}) + "\n")
        protocol.flush()
        continue
    move = agent.get_move(request["fen"], request["time_left_ms"])
    protocol.write(json.dumps({"move": move}) + "\n")
    protocol.flush()
