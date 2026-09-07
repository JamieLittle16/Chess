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
text = text.replace(old, new, 1)

# This existing test is specifically about a rook being closed by its own pawn. Once passed-pawn
# scoring exists, the old lone a2 pawn is itself a passer, so `(0, 0)` no longer isolates the rook
# term. Add an enemy a3 pawn only to the fixture so the white pawn is not passed; runtime code is
# unchanged by this compatibility repair.
old_fixture = '''        let closed = Position::from_fen("7k/8/8/8/8/8/P7/R6K w - - 0 1").expect("valid FEN");'''
new_fixture = '''        let closed = Position::from_fen("7k/8/8/8/8/p7/P7/R6K w - - 0 1").expect("valid FEN");'''
if text.count(old_fixture) != 1:
    raise SystemExit("closed-rook fixture anchor missing")
text = text.replace(old_fixture, new_fixture, 1)

path.write_text(text)
