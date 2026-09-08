#!/usr/bin/env python3
"""Apply the M6 History-v2 search experiment to current production source.

The committed branch contains only semantics-neutral substrate. Qualification builds call this
script to activate either:

* history: main + one-ply continuation history with once-scored quiet ordering; or
* history-lmr: the same ordering/training plus conservative history-conditioned LMR.

Every source edit is guarded by an exact occurrence count so drift fails loudly.
"""

from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def patch_search(*, history_lmr: bool) -> None:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """mod move_picker;\nmod quiescence;\nmod root_analysis;\n""",
        """mod history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n""",
        label="history module",
    )
    text = replace_exact(
        text,
        "use move_picker::MovePicker;",
        """use history::{HistoryTables, MoveContext, depth_bonus};\nuse move_picker::MovePicker;""",
        label="history imports",
    )

    text = replace_exact(
        text,
        """    path_keys: [u64; MAX_SEARCH_PLY],\n    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n    gestalt: Option<GestaltSearchEvaluator>,\n}""",
        """    path_keys: [u64; MAX_SEARCH_PLY],\n    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n    history: HistoryTables,\n    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],\n    gestalt: Option<GestaltSearchEvaluator>,\n}""",
        label="Searcher history fields",
    )
    text = replace_exact(
        text,
        """            path_keys: [0; MAX_SEARCH_PLY],\n            killers: [[None; 2]; MAX_SEARCH_PLY],\n            gestalt: GestaltSearchEvaluator::from_environment(),\n""",
        """            path_keys: [0; MAX_SEARCH_PLY],\n            killers: [[None; 2]; MAX_SEARCH_PLY],\n            history: HistoryTables::new(),\n            move_contexts: [None; MAX_SEARCH_PLY],\n            gestalt: GestaltSearchEvaluator::from_environment(),\n""",
        label="Searcher history construction",
    )

    fixed_reset = """        self.nodes = 1;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n"""
    text = replace_exact(
        text,
        fixed_reset,
        """        self.nodes = 1;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.history.clear();\n        self.move_contexts = [None; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n""",
        label="fixed-depth history reset",
    )
    iterative_reset = """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n        let mut last_completed = None;\n"""
    text = replace_exact(
        text,
        iterative_reset,
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.history.clear();\n        self.move_contexts = [None; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n        let mut last_completed = None;\n""",
        label="iterative history reset",
    )

    root_picker = """        let mut moves = moves;\n        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);\n        let mut first_move = true;\n        while let Some(mv) = picker.next(position) {\n            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n"""
    text = replace_exact(
        text,
        root_picker,
        """        let mut moves = moves;\n        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);\n        let mut first_move = true;\n        while let Some(mv) = picker.next_scored(position, &mut |mv| {\n            let context = move_context(position, mv);\n            self.history.score(position.side_to_move(), None, context)\n        }) {\n            let context = move_context(position, mv);\n            self.move_contexts[0] = Some(context);\n            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n""",
        label="root history ordering",
    )

    picker = """        let mut moves = moves;\n        let killers = self.killers[usize::from(ply)];\n        let mut picker = MovePicker::new(&mut moves, hint, killers);\n        let mut first_move = true;\n        let mut move_index = 0usize;\n        while let Some(mv) = picker.next(position) {\n            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();\n            let protected_killer = killers.contains(&Some(mv));\n            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n"""
    text = replace_exact(
        text,
        picker,
        """        let mut moves = moves;\n        let killers = self.killers[usize::from(ply)];\n        let mut picker = MovePicker::new(&mut moves, hint, killers);\n        let mut first_move = true;\n        let mut move_index = 0usize;\n        let previous_context = if ply == 0 {\n            None\n        } else {\n            self.move_contexts[usize::from(ply - 1)]\n        };\n        while let Some(mv) = picker.next_scored(position, &mut |mv| {\n            let context = move_context(position, mv);\n            self.history\n                .score(position.side_to_move(), previous_context, context)\n        }) {\n            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();\n            let protected_killer = killers.contains(&Some(mv));\n            let side = position.side_to_move();\n            let context = move_context(position, mv);\n            self.move_contexts[usize::from(ply)] = Some(context);\n            let prepared = self.prepare_leaf_move(position, mv);\n            let undo = position.make_move(mv);\n""",
        label="negamax history ordering",
    )

    score_site = """            let score = -child?;\n            first_move = false;\n            move_index = move_index.saturating_add(1);\n\n            if score > best {\n"""
    text = replace_exact(
        text,
        score_site,
        """            let score = -child?;\n            first_move = false;\n            move_index = move_index.saturating_add(1);\n\n            // Train only on scout-node evidence. Quiet fail-highs receive a strong positive\n            // gravity update; searched quiets that fail to cut receive a smaller malus.\n            if quiet && null_window {\n                let bonus = depth_bonus(depth);\n                let update = if score >= beta { bonus } else { -(bonus / 2) };\n                self.history\n                    .update(side, previous_context, context, update);\n            }\n\n            if score > best {\n""",
        label="history training",
    )

    helper_anchor = "fn has_reverse_futility_material(position: &Position) -> bool {\n"
    text = replace_exact(
        text,
        helper_anchor,
        """fn move_context(position: &Position, mv: ChessMove) -> MoveContext {\n    let piece = position\n        .piece_at(mv.from())\n        .expect(\"generated legal move has a moving piece\");\n    MoveContext::new(piece.kind(), mv.to())\n}\n\nfn has_reverse_futility_material(position: &Position) -> bool {\n""",
        label="move-context helper",
    )

    if history_lmr:
        old_reduction = """                let reduction = if !in_check && quiet && !protected_killer && !gives_check {\n                    lmr_v3_reduction(depth, move_index)\n                } else {\n                    0\n                };\n"""
        new_reduction = """                let reduction = if !in_check && quiet && !protected_killer && !gives_check {\n                    history_adjusted_lmr_reduction(\n                        depth,\n                        move_index,\n                        self.history.score(side, previous_context, context),\n                    )\n                } else {\n                    0\n                };\n"""
        text = replace_exact(
            text,
            old_reduction,
            new_reduction,
            label="history-conditioned LMR call",
        )

        lmr_helper = """fn lmr_v3_reduction(depth: u8, move_index: usize) -> u8 {\n    if depth >= 9 && move_index >= 12 {\n        3\n    } else if depth >= 6 && move_index >= 8 {\n        2\n    } else if depth >= 3 && move_index >= 4 {\n        1\n    } else {\n        0\n    }\n}\n"""
        text = replace_exact(
            text,
            lmr_helper,
            lmr_helper
            + """\nfn history_adjusted_lmr_reduction(depth: u8, move_index: usize, history_score: i32) -> u8 {\n    let base = lmr_v3_reduction(depth, move_index);\n    if history_score >= 4_096 {\n        return base.saturating_sub(1);\n    }\n    if history_score <= -4_096 && depth >= 5 && move_index >= 4 {\n        return base.saturating_add(1).min(3);\n    }\n    base\n}\n""",
            label="history-conditioned LMR helper",
        )

    path.write_text(text, encoding="utf-8")


def patch_root_analysis() -> None:
    path = Path("crates/chess-search/src/root_analysis.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        // Root analysis must use the same derived learned-evaluation state as ordinary search.\n""",
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.history.clear();\n        self.move_contexts = [None; MAX_SEARCH_PLY];\n        // Root analysis must use the same derived learned-evaluation state as ordinary search.\n""",
        label="root-analysis history reset",
    )
    text = replace_exact(
        text,
        """        for order in 0..moves.len() {\n            let mv = moves[order];\n            let prepared = self.prepare_leaf_move(position, mv);\n""",
        """        for order in 0..moves.len() {\n            let mv = moves[order];\n            self.move_contexts[0] = Some(super::move_context(position, mv));\n            let prepared = self.prepare_leaf_move(position, mv);\n""",
        label="root-analysis predecessor context",
    )

    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("history", "history-lmr"), default="history")
    args = parser.parse_args()

    patch_search(history_lmr=args.variant == "history-lmr")
    patch_root_analysis()
    print(f"applied M6 History-v2 candidate: {args.variant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
