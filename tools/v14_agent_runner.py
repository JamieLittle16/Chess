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


def reset() -> None:
    agent._GAME_KEYS = []
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(np.uint64(0))
    agent._HASH_MOVES.fill(np.int32(-1))
    agent._TT_TABLE.fill(np.uint64(0))


protocol.write('{"ready":true}\n')
protocol.flush()
for line in sys.stdin:
    q = json.loads(line)
    if q.get("reset") is True:
        reset()
        protocol.write('{"reset":true}\n')
        protocol.flush()
        continue
    protocol.write(json.dumps({"move": agent.get_move(q["fen"], q["time_left_ms"])}) + "\n")
    protocol.flush()
