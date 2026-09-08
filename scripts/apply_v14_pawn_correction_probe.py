#!/usr/bin/env python3
"""Activate V14 pawn correction history after the History-v2 history-LMR patch.

The committed correction table is dormant. Qualification builds first run
`apply_history_v2_probe.py --variant history-lmr`, then this patcher wires the bounded pawn-structure
correction into shallow futility evaluation and learns from quiet search residuals.
"""

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise PatchError(f"{label}: expected 1 occurrence, found {count}")
    return text.replace(old, new, 1)


def patch_search() -> None:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        "mod history;\nmod move_picker;",
        "mod correction;\nmod history;\nmod move_picker;",
        label="correction module",
    )
    text = replace_exact(
        text,
        "use history::{HistoryTables, MoveContext, depth_bonus};",
        "use correction::PawnCorrectionHistory;\nuse history::{HistoryTables, MoveContext, depth_bonus};",
        label="correction import",
    )
    text = replace_exact(
        text,
        """    history: HistoryTables,
    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],
    gestalt: Option<GestaltSearchEvaluator>,
""",
        """    history: HistoryTables,
    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],
    correction: PawnCorrectionHistory,
    gestalt: Option<GestaltSearchEvaluator>,
""",
        label="correction field",
    )
    text = replace_exact(
        text,
        """            history: HistoryTables::new(),
            move_contexts: [None; MAX_SEARCH_PLY],
            gestalt: GestaltSearchEvaluator::from_environment(),
""",
        """            history: HistoryTables::new(),
            move_contexts: [None; MAX_SEARCH_PLY],
            correction: PawnCorrectionHistory::new(),
            gestalt: GestaltSearchEvaluator::from_environment(),
""",
        label="correction construction",
    )

    text = text.replace(
        """        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        self.reset_leaf_evaluator(position);
""",
        """        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        self.correction.clear();
        self.reset_leaf_evaluator(position);
""",
    )
    if text.count("self.correction.clear();") != 2:
        raise PatchError(
            "top-level correction resets: expected fixed-depth and iterative-deepening resets"
        )

    old_eval = """        let pruning_static_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            Some(evaluate(position))
        } else {
            None
        };
        if let Some(static_eval) = pruning_static_eval {
"""
    new_eval = """        let raw_pruning_static_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            Some(evaluate(position))
        } else {
            None
        };
        let pruning_static_eval = raw_pruning_static_eval
            .map(|raw| self.correction.corrected_eval(position, raw));
        if let Some(static_eval) = pruning_static_eval {
"""
    text = replace_exact(text, old_eval, new_eval, label="corrected pruning static eval")

    bound_anchor = """        let bound = if best <= alpha_original {
"""
    correction_update = """        // Train only from shallow scout nodes where we already paid for the raw classical
        // pruning evaluation. Quiet best moves are the clean positional signal; captures/promotions
        // are deliberately excluded so tactical swings do not pollute pawn-structure correction.
        if let Some(raw_eval) = raw_pruning_static_eval
            && best.abs() < MATE_TT_THRESHOLD
            && best_move.is_some_and(|mv| !mv.kind().is_capture() && !mv.kind().is_promotion())
        {
            self.correction.update(position, raw_eval, best, depth);
        }

""" + bound_anchor
    text = replace_exact(text, bound_anchor, correction_update, label="correction update")

    path.write_text(text, encoding="utf-8")


def patch_root_analysis() -> None:
    path = Path("crates/chess-search/src/root_analysis.rs")
    text = path.read_text(encoding="utf-8")
    old = """        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        // Root analysis must use the same derived learned-evaluation state as ordinary search.
"""
    new = """        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        self.correction.clear();
        // Root analysis must use the same derived learned-evaluation state as ordinary search.
"""
    text = replace_exact(text, old, new, label="root-analysis correction reset")
    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_search()
    patch_root_analysis()
    print("applied V14 pawn correction-history candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
