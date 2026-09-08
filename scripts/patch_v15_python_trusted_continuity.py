#!/usr/bin/env python3
"""Trust the competition's one-process-per-game contract instead of re-enumerating opponent replies.

The exact V14 wrapper already documents this as the official platform contract. Defensive continuity
verification was useful while harness semantics were uncertain, but it generates every legal reply
and push/pops each until the incoming FEN matches. In production a non-empty game history therefore
means continuation; qualification runners explicitly reset state between games.
"""
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='    continued = bool(_GAME_KEYS) and _is_expected_opponent_reply(board)\n'
new='    continued = bool(_GAME_KEYS)\n'
if s.count(old)!=1: raise SystemExit(f'continuity call count={s.count(old)}')
p.write_text(s.replace(old,new,1))
