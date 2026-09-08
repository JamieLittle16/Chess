#!/usr/bin/env python3
"""Use the qualified V13 prefix for the pre-deadline emergency root fallback only.

Normal iterative search remains byte-for-byte semantically unchanged after the deadline starts. The
fallback is used only if no depth completes; preserving its draw/mate logic while omitting the H64
tail removes full-student work that is otherwise paid for every legal root move before timing begins.
"""
from pathlib import Path
import sys

p = Path(sys.argv[1])
s = p.read_text()
start = s.index("def iterative_search_stateful_timed_cached(")
end = s.index("\n\n@njit(cache=False)\ndef iterative_search_stateful_timed(", start)
head, block, tail = s[:start], s[start:end], s[end:]
old_advance = "        _advance_eval_state_into(board, side, move, eval_stack[0], eval_stack[1])\n"
new_advance = """        _advance_eval_state_into(
            board, side, move, eval_stack[0, :EVAL_V13_WIDTH], eval_stack[1, :EVAL_V13_WIDTH]
        )
"""
if block.count(old_advance) != 1:
    raise SystemExit(f"timed fallback advance count={block.count(old_advance)}")
block = block.replace(old_advance, new_advance, 1)
old_eval = "                fallback_score = -_evaluate_state(-side, eval_stack[1])\n"
new_eval = "                fallback_score = -_evaluate_state_v13_only(-side, eval_stack[1])\n"
if block.count(old_eval) != 1:
    raise SystemExit(f"timed fallback eval count={block.count(old_eval)}")
block = block.replace(old_eval, new_eval, 1)
p.write_text(head + block + tail)
