#!/usr/bin/env python3
"""Keep searching past the soft deadline when V13 and H64 disagree at the root.

The hard clock boundary is untouched. The full and V13-only evaluators are both already present in
V14; this patch computes their root disagreement once per move and permits the existing stable-root
soft stop only when disagreement is at or below the supplied centipawn threshold.
"""
from pathlib import Path
import sys

if len(sys.argv) != 3:
    raise SystemExit("usage: patch_v15_python_disagreement_time.py SEARCH.py THRESHOLD_CP")
p=Path(sys.argv[1]); threshold=int(sys.argv[2]); s=p.read_text()
start=s.index("def iterative_search_stateful_timed_cached(")
end=s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful_timed(",start)
head,block,tail=s[:start],s[start:end],s[end:]
anchor="""    _build_eval_state_into(board, eval_stack[0])\n    path_keys[0] = position_key(board, side, castling, ep_square)\n"""
replacement="""    _build_eval_state_into(board, eval_stack[0])\n    root_eval_disagreement = abs(\n        _evaluate_state(side, eval_stack[0]) - _evaluate_state_v13_only(side, eval_stack[0])\n    )\n    path_keys[0] = position_key(board, side, castling, ep_square)\n"""
if block.count(anchor)!=1:raise SystemExit(f'root eval anchor count={block.count(anchor)}')
block=block.replace(anchor,replacement,1)
old="""        if depth >= 6 and now_ticks >= soft_deadline and stable_transitions >= 2:\n            break\n"""
new=f"""        if (\n            depth >= 6\n            and now_ticks >= soft_deadline\n            and stable_transitions >= 2\n            and root_eval_disagreement <= {threshold}\n        ):\n            break\n"""
if block.count(old)!=1:raise SystemExit(f'soft-stop anchor count={block.count(old)}')
block=block.replace(old,new,1)
p.write_text(head+block+tail)
