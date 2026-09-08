#!/usr/bin/env python3
"""Apply the research-only incremental gestalt search integration.

The accepted production search source remains untouched in git. Qualification workflows apply this
script to a clean checkout, build the candidate, and retain the resulting source diff as evidence.
Every replacement is count-checked so source drift fails loudly instead of silently producing a
partially integrated evaluator.
"""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def replace_all_exact(text: str, old: str, new: str, *, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new)


def patch_search() -> None:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        "use chess_eval::evaluate;",
        """use chess_eval::{
    evaluate,
    gestalt::{
        AccumulatorState as GestaltAccumulatorState, Network as GestaltNetwork,
        PreparedAccumulatorUpdate as GestaltPreparedUpdate,
    },
};""",
        label="gestalt imports",
    )

    never_stop = """impl SearchControl for NeverStop {
    fn should_stop(&self, _nodes: u64) -> bool {
        false
    }
}
"""
    evaluator = never_stop + """
struct GestaltSearchEvaluator {
    network: GestaltNetwork,
    accumulator: Option<GestaltAccumulatorState>,
}

impl GestaltSearchEvaluator {
    fn from_environment() -> Option<Self> {
        let path = std::env::var_os("CHESS_GESTALT_NETWORK")?;
        let network = GestaltNetwork::from_file(std::path::Path::new(&path))
            .unwrap_or_else(|error| panic!("failed to load CHESS_GESTALT_NETWORK: {error}"));
        Some(Self {
            network,
            accumulator: None,
        })
    }
}
"""
    text = replace_exact(text, never_stop, evaluator, label="evaluator state insertion")

    text = replace_exact(
        text,
        """    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
}""",
        """    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    gestalt: Option<GestaltSearchEvaluator>,
}""",
        label="Searcher gestalt field",
    )

    text = replace_exact(
        text,
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
        }""",
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            gestalt: GestaltSearchEvaluator::from_environment(),
        }""",
        label="Searcher constructor",
    )

    capacity_method = """    pub fn tt_capacity_entries(&self) -> usize {
        self.table.len()
    }
"""
    evaluator_methods = capacity_method + """
    fn reset_leaf_evaluator(&mut self, position: &Position) {
        if let Some(gestalt) = &mut self.gestalt {
            gestalt.accumulator = Some(
                GestaltAccumulatorState::from_position(&gestalt.network, position)
                    .expect("legal search root has both kings"),
            );
        }
    }

    fn leaf_evaluate(&self, position: &Position) -> i32 {
        if let Some(gestalt) = &self.gestalt
            && let Some(accumulator) = &gestalt.accumulator
        {
            return accumulator.evaluate(&gestalt.network, position.side_to_move());
        }
        evaluate(position)
    }

    fn prepare_leaf_move(
        &self,
        position: &Position,
        mv: ChessMove,
    ) -> Option<GestaltPreparedUpdate> {
        self.gestalt.as_ref().map(|_| {
            GestaltAccumulatorState::prepare_move(position, mv)
                .expect("generated legal move has a valid gestalt update")
        })
    }

    fn apply_leaf_move(&mut self, position: &Position, prepared: Option<GestaltPreparedUpdate>) {
        if let Some(prepared) = prepared
            && let Some(gestalt) = &mut self.gestalt
        {
            gestalt
                .accumulator
                .as_mut()
                .expect("gestalt root state was initialised")
                .apply_prepared(&gestalt.network, position, prepared)
                .expect("legal child position has valid gestalt state");
        }
    }

    fn restore_leaf_move(
        &mut self,
        position: &Position,
        prepared: Option<GestaltPreparedUpdate>,
    ) {
        if let Some(prepared) = prepared
            && let Some(gestalt) = &mut self.gestalt
        {
            gestalt
                .accumulator
                .as_mut()
                .expect("gestalt root state was initialised")
                .restore_after_unmake(&gestalt.network, position, prepared)
                .expect("restored legal position has valid gestalt state");
        }
    }
"""
    text = replace_exact(
        text,
        capacity_method,
        evaluator_methods,
        label="evaluator helper methods",
    )

    text = replace_all_exact(
        text,
        """        self.killers = [[None; 2]; MAX_SEARCH_PLY];
""",
        """        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.reset_leaf_evaluator(position);
""",
        count=2,
        label="root evaluator initialisation",
    )

    text = replace_exact(
        text,
        """        if depth == 0 {
            let score = evaluate(position);
""",
        """        if depth == 0 {
            let score = self.leaf_evaluate(position);
""",
        label="depth-zero root leaf",
    )

    text = replace_exact(
        text,
        """        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {
""",
        """        while let Some(mv) = picker.next(position) {
            let prepared = self.prepare_leaf_move(position, mv);
            let undo = position.make_move(mv);
            self.apply_leaf_move(position, prepared);
            let child = if first_move {
""",
        label="root move push",
    )

    text = replace_exact(
        text,
        """            let protected_killer = killers.contains(&Some(mv));
            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
""",
        """            let protected_killer = killers.contains(&Some(mv));
            let prepared = self.prepare_leaf_move(position, mv);
            let undo = position.make_move(mv);
            self.apply_leaf_move(position, prepared);
            let gives_check = position.is_in_check(position.side_to_move());
""",
        label="negamax move push",
    )

    text = replace_exact(
        text,
        """                position.unmake_move(mv, undo);
                move_index = move_index.saturating_add(1);
                continue;
""",
        """                position.unmake_move(mv, undo);
                self.restore_leaf_move(position, prepared);
                move_index = move_index.saturating_add(1);
                continue;
""",
        label="late-futility evaluator restore",
    )

    text = replace_all_exact(
        text,
        """            position.unmake_move(mv, undo);
            let score = -child?;
""",
        """            position.unmake_move(mv, undo);
            self.restore_leaf_move(position, prepared);
            let score = -child?;
""",
        count=2,
        label="root and negamax evaluator restores",
    )

    text = replace_exact(
        text,
        """        } else {
            (Some(moves[0]), evaluate(position))
        };
""",
        """        } else {
            (Some(moves[0]), self.leaf_evaluate(position))
        };
""",
        label="fallback learned leaf",
    )

    # Deliberately leave the accepted RFP/futility static-eval call on chess_eval::evaluate. The
    # mature net scores actual leaves; classical remains a pruning safety oracle until scale-specific
    # pruning is independently qualified.
    pruning = "Some(evaluate(position))"
    if text.count(pruning) != 1:
        raise PatchError(
            f"classical pruning oracle: expected exactly one remaining {pruning!r}, "
            f"found {text.count(pruning)}"
        )

    path.write_text(text, encoding="utf-8")


def patch_quiescence() -> None:
    path = Path("crates/chess-search/src/quiescence.rs")
    text = path.read_text(encoding="utf-8")

    if text.count("evaluate(position)") != 4:
        raise PatchError(
            "qsearch leaves: expected four classical leaf calls, "
            f"found {text.count('evaluate(position)')}"
        )
    text = text.replace("evaluate(position)", "self.leaf_evaluate(position)")

    text = replace_exact(
        text,
        """        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            self.nodes = self.nodes.saturating_add(1);
""",
        """        while let Some(mv) = picker.next(position) {
            let prepared = self.prepare_leaf_move(position, mv);
            let undo = position.make_move(mv);
            self.apply_leaf_move(position, prepared);
            self.nodes = self.nodes.saturating_add(1);
""",
        label="qsearch move push",
    )

    text = replace_exact(
        text,
        """            position.unmake_move(mv, undo);
            let score = -child?;
""",
        """            position.unmake_move(mv, undo);
            self.restore_leaf_move(position, prepared);
            let score = -child?;
""",
        label="qsearch evaluator restore",
    )

    # Tests intentionally compare against the classical control and therefore must be updated to the
    # same helper only inside the implementation, not rewritten globally beyond the four production
    # leaf sites. The four replacements above include test references only if source shape drifts,
    # which the count check prevents.
    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_search()
    patch_quiescence()
    print("applied incremental gestalt leaf/qsearch probe; classical pruning oracle retained")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
