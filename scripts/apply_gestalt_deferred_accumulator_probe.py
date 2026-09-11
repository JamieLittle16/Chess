#!/usr/bin/env python3
"""Materialize the M6 deferred-accumulator research candidate.

The production search currently advances the learned-evaluator accumulator immediately after
making every generated move. Late-quiet futility can reject a move before any child search or
learned evaluation occurs, so those accumulator writes (and the matching restore) are wasted.

This patch keeps the prepared update cheap and fixed-size, but delays applying it until the move
has survived the existing late-quiet futility gate. Search semantics, node counts, pruning inputs,
and learned scores are unchanged.
"""

from pathlib import Path

PATH = Path("crates/chess-search/src/lib.rs")

OLD = """            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n            self.apply_leaf_move(position, prepared);\n            let gives_check = position.is_in_check(position.side_to_move());\n            if let Some(static_eval) = pruning_static_eval\n                && should_prune_late_quiet_futility(\n                    depth,\n                    move_index,\n                    in_check,\n                    null_window,\n                    quiet,\n                    protected_killer,\n                    gives_check,\n                    static_eval,\n                    alpha,\n                    beta,\n                )\n            {\n                position.unmake_move(mv, undo);\n                self.restore_leaf_move(position, prepared);\n                move_index = move_index.saturating_add(1);\n                continue;\n            }\n            let child = if first_move {\n"""

NEW = """            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n            let gives_check = position.is_in_check(position.side_to_move());\n            if let Some(static_eval) = pruning_static_eval\n                && should_prune_late_quiet_futility(\n                    depth,\n                    move_index,\n                    in_check,\n                    null_window,\n                    quiet,\n                    protected_killer,\n                    gives_check,\n                    static_eval,\n                    alpha,\n                    beta,\n                )\n            {\n                // The learned accumulator is derived state and has not been advanced yet. A move\n                // rejected by late-quiet futility never enters child search, so avoid touching both\n                // 1,536-lane perspective accumulators only to restore them immediately afterwards.\n                position.unmake_move(mv, undo);\n                move_index = move_index.saturating_add(1);\n                continue;\n            }\n            self.apply_leaf_move(position, prepared);\n            let child = if first_move {\n"""

text = PATH.read_text()
count = text.count(OLD)
if count != 1:
    raise SystemExit(f"expected exactly one production search seam, found {count}")
PATH.write_text(text.replace(OLD, NEW, 1))
print("applied deferred gestalt accumulator update after late-quiet futility gate")
