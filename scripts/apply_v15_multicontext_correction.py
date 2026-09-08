#!/usr/bin/env python3
"""Materialize the V15 multi-context Gestalt correction-history research candidate."""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, label: str, count: int = 1) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        "mod history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n",
        "mod correction_history;\nmod history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n",
        label="correction module",
    )
    text = replace_exact(
        text,
        "use history::{HistoryTables, MoveContext, depth_bonus};\n",
        "use correction_history::MultiContextCorrectionHistory;\nuse history::{HistoryTables, MoveContext, depth_bonus};\n",
        label="correction import",
    )
    text = replace_exact(
        text,
        """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    history: HistoryTables,
""",
        """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    correction_history: MultiContextCorrectionHistory,
    history: HistoryTables,
""",
        label="Searcher correction field",
    )
    text = replace_exact(
        text,
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            history: HistoryTables::new(),
""",
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            correction_history: MultiContextCorrectionHistory::new(),
            history: HistoryTables::new(),
""",
        label="Searcher correction construction",
    )

    old_leaf = """    fn leaf_evaluate(&self, position: &Position) -> i32 {
        if let Some(gestalt) = &self.gestalt
            && let Some(accumulator) = &gestalt.accumulator
        {
            return accumulator.evaluate(&gestalt.network, position.side_to_move());
        }
        evaluate(position)
    }
"""
    new_leaf = """    fn raw_leaf_evaluate(&self, position: &Position) -> i32 {
        if let Some(gestalt) = &self.gestalt
            && let Some(accumulator) = &gestalt.accumulator
        {
            return accumulator.evaluate(&gestalt.network, position.side_to_move());
        }
        evaluate(position)
    }

    fn corrected_leaf_evaluate(&self, position: &Position, raw: i32) -> i32 {
        if self.gestalt.is_some() {
            raw.saturating_add(self.correction_history.correction(position))
        } else {
            // The classical fallback is a control path and must remain behaviorally identical.
            raw
        }
    }

    fn leaf_evaluate(&self, position: &Position) -> i32 {
        let raw = self.raw_leaf_evaluate(position);
        self.corrected_leaf_evaluate(position, raw)
    }
"""
    text = replace_exact(text, old_leaf, new_leaf, label="raw/corrected leaf split")

    old_pruning = """        let pruning_static_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            Some(self.leaf_evaluate(position))
        } else {
            None
        };
"""
    new_pruning = """        let pruning_raw_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            Some(self.raw_leaf_evaluate(position))
        } else {
            None
        };
        let pruning_static_eval = pruning_raw_eval
            .map(|raw| self.corrected_leaf_evaluate(position, raw));
"""
    text = replace_exact(text, old_pruning, new_pruning, label="pruning correction")

    old_bound = """        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };
        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
"""
    new_bound = """        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };
        if depth >= 2
            && let Some(raw_eval) = pruning_raw_eval
            && best.abs() < MATE_TT_THRESHOLD
            && best_move.is_some_and(|mv| !mv.kind().is_capture() && !mv.kind().is_promotion())
        {
            // Learn only when the alpha-beta bound supports the residual direction. This avoids
            // teaching a lower-bound fail-high as if it were an exact score (and vice versa).
            let residual = best.saturating_sub(raw_eval);
            let supported = match bound {
                Bound::Exact => true,
                Bound::Lower => residual > 0,
                Bound::Upper => residual < 0,
            };
            if supported && residual.abs() >= 12 {
                self.correction_history.update(position, residual, depth);
            }
        }
        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
"""
    text = replace_exact(text, old_bound, new_bound, label="bound-aware correction learning")

    path.write_text(text, encoding="utf-8")
    print("applied V15 multi-context Gestalt correction history")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
