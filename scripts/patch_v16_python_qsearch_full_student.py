#!/usr/bin/env python3
"""Keep the packaged V14 H64 student live at every stable quiescence node.

Packaged V14 deliberately drops to the exact V13 prefix below qply 0 and passes only the first eight
evaluation cells through qsearch move transport. That saves some work, but it means capture/
recapture descendants are judged by a weaker evaluator than the nominal leaf. Rust V15 keeps its
learned evaluator live throughout qsearch. This patch restores that semantic parity while retaining
all existing qsearch move-generation and ceiling policy.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("path", type=Path)
    args = parser.parse_args()

    text = args.path.read_text()

    old = """    if not checked:\n        if qply == 0:\n            stand_pat = _evaluate_state(side, eval_stack[ply])\n        else:\n            stand_pat = _evaluate_state_v13_only(side, eval_stack[ply])\n        if stand_pat >= beta:\n"""
    new = """    if not checked:\n        # Keep the V14 H64 student live at every stable quiescence node. Tactical children already\n        # have exact incremental absolute768 transport available; dropping to V13 below qply 0\n        # weakens the evaluator precisely after capture/recapture sequences.\n        stand_pat = _evaluate_state(side, eval_stack[ply])\n        if stand_pat >= beta:\n"""
    if text.count(old) != 1:
        raise SystemExit(f"qsearch stand-pat anchor count={text.count(old)}")
    text = text.replace(old, new, 1)

    old = """        # Only the exact V13 prefix is live below qply 0. Passing 8-cell slices means the existing\n        # qualified incremental updater performs no work in its appended student-accumulator tail.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply, :EVAL_V13_WIDTH],\n            eval_stack[ply + 1, :EVAL_V13_WIDTH],\n        )\n"""
    new = """        # Preserve the full V14 evaluator state through tactical qsearch moves so every stable\n        # descendant is judged with the same H64 student as the nominal leaf.\n        _advance_eval_state_into(\n            board,\n            side,\n            move,\n            eval_stack[ply],\n            eval_stack[ply + 1],\n        )\n"""
    if text.count(old) != 1:
        raise SystemExit(f"qsearch transport anchor count={text.count(old)}")
    text = text.replace(old, new, 1)

    args.path.write_text(text)
    print("patched full V14 H64 evaluator through quiescence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
