#!/usr/bin/env python3
"""Materialize the frozen passed-pawn race v2 candidate with conservative king catchability."""
from pathlib import Path
import runpy

runpy.run_path("tools/apply_passed_pawn_race_v2_over_rfp.py", run_name="__main__")
path = Path("crates/chess-eval/src/lib.rs")
text = path.read_text()
old = '''    let king_moves_before_promotion = pushes_to_promote.saturating_sub(usize::from(
        position.side_to_move() == color,
    ));'''
new = '''    // Stay conservative about declaring a runner unstoppable: give the enemy king the full
    // number of remaining pawn pushes to enter the promotion square, irrespective of side to move.
    let king_moves_before_promotion = pushes_to_promote;'''
if text.count(old) != 1:
    raise SystemExit("king-square tempo anchor missing")
path.write_text(text.replace(old, new, 1))
