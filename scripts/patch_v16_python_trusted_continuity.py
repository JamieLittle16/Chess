#!/usr/bin/env python3
"""Trust the competition's one-process-per-game contract.

The packaged Python engine otherwise verifies continuity by enumerating every legal opponent
reply and push/popping until the incoming FEN matches. Qualification runners explicitly reset
between games, so once the per-game history is non-empty the next call is a continuation.
"""
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_v16_python_trusted_continuity.py AGENT.py")

p = Path(sys.argv[1])
s = p.read_text()
old = "    continued = bool(_GAME_KEYS) and _is_expected_opponent_reply(board)\n"
new = "    continued = bool(_GAME_KEYS)\n"
if s.count(old) != 1:
    raise SystemExit(f"continuity call count={s.count(old)}")
p.write_text(s.replace(old, new, 1))
