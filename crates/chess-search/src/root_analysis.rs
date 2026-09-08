//! Objective root-candidate analysis for practical selection research.
//!
//! This module is deliberately off the ordinary `bestmove` hot path. It exposes several
//! objectively searched root alternatives so later opponent/time-pressure selectors can operate
//! inside a hard safety envelope without redefining evaluation or normal search semantics.

use chess_core::{ChessMove, Position, generate_legal_moves_mut};

use super::{INFINITY, MAX_SEARCH_PLY, NeverStop, Searcher, is_rule_draw};

/// One legal root move with its exact score at the requested nominal search depth.
///
/// Scores use the same side-to-move convention as [`super::SearchResult`]. Consumers must not treat
/// the ordering here as permission to select an objectively inferior move; a practical selector is
/// expected to apply an explicit safety envelope first.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct RootCandidate {
    pub mv: ChessMove,
    pub score: i32,
}

impl Searcher {
    /// Return up to `max_candidates` objectively scored legal root alternatives.
    ///
    /// This is an analysis API, not the normal tournament search path. Every legal root move is
    /// searched with a full window before ranking, so the returned scores are directly comparable.
    /// Ties preserve legal-generator order for deterministic behaviour. `depth == 0` and
    /// `max_candidates == 0` return an empty list rather than inventing a root-move score.
    #[must_use]
    pub fn analyze_root_candidates(
        &mut self,
        position: &mut Position,
        depth: u8,
        max_candidates: usize,
    ) -> Vec<RootCandidate> {
        self.analyze_root_candidates_with_history(position, &[], depth, max_candidates)
    }

    /// Root-candidate analysis with repetition keys for positions preceding `position`.
    #[must_use]
    pub fn analyze_root_candidates_with_history(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        max_candidates: usize,
    ) -> Vec<RootCandidate> {
        if depth == 0 || max_candidates == 0 {
            return Vec::new();
        }

        #[cfg(debug_assertions)]
        let root = position.clone();

        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        // Root analysis must use the same derived learned-evaluation state as ordinary search.
        // Rebuild at the supplied root even when the Searcher was previously used on another
        // position; otherwise a configured Gestalt evaluator could fall back to classical scoring
        // or, worse, reuse a stale accumulator from an unrelated root.
        self.reset_leaf_evaluator(position);

        let repetition_key = position.repetition_key().raw();
        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            return Vec::new();
        }

        // At a claimable root draw every legal continuation is dominated by the available draw for
        // objective purposes. Keep deterministic generator order and do not pretend one move has a
        // different searched value merely because we declined the claim while analysing it.
        if is_rule_draw(position, repetition_key, prior_history, &[]) {
            let count = max_candidates.min(moves.len());
            return (0..count)
                .map(|index| RootCandidate {
                    mv: moves[index],
                    score: 0,
                })
                .collect();
        }

        self.path_keys[0] = repetition_key;
        let mut ranked = Vec::with_capacity(moves.len());

        for order in 0..moves.len() {
            let mv = moves[order];
            self.move_contexts[0] = Some(super::move_context(position, mv));
            let prepared = self.prepare_leaf_move(position, mv);
            let undo = position.make_move(mv);
            self.apply_leaf_move(position, prepared);
            let child = self
                .negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -INFINITY,
                    INFINITY,
                    1,
                    1,
                    &NeverStop,
                )
                .expect("NeverStop cannot interrupt root-candidate analysis");
            position.unmake_move(mv, undo);
            self.restore_leaf_move(position, prepared);
            ranked.push((order, RootCandidate { mv, score: -child }));
        }

        ranked.sort_by(|(left_order, left), (right_order, right)| {
            right
                .score
                .cmp(&left.score)
                .then_with(|| left_order.cmp(right_order))
        });
        ranked.truncate(max_candidates.min(ranked.len()));

        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);

        ranked.into_iter().map(|(_, candidate)| candidate).collect()
    }
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::*;

    #[test]
    fn root_analysis_is_bounded_sorted_unique_and_restores_position() {
        let original = Position::startpos();
        let mut position = original.clone();
        let legal = position.legal_moves();
        let mut searcher = Searcher::with_tt_entries(1 << 12);

        let candidates = searcher.analyze_root_candidates(&mut position, 2, 5);

        assert_eq!(candidates.len(), 5);
        assert_eq!(position, original);
        assert!(
            candidates
                .windows(2)
                .all(|pair| pair[0].score >= pair[1].score)
        );
        for (index, candidate) in candidates.iter().enumerate() {
            assert!(legal.contains(&candidate.mv));
            assert!(
                !candidates[..index]
                    .iter()
                    .any(|seen| seen.mv == candidate.mv)
            );
        }
    }

    #[test]
    fn top_root_candidate_matches_objective_depth_search() {
        let mut analysis_position = Position::startpos();
        let mut objective_position = analysis_position.clone();
        let mut analysis_searcher = Searcher::with_tt_entries(1 << 12);
        let mut objective_searcher = Searcher::with_tt_entries(1 << 12);

        let candidates = analysis_searcher.analyze_root_candidates(&mut analysis_position, 2, 20);
        let objective = objective_searcher.search_depth(&mut objective_position, 2);

        assert!(!candidates.is_empty());
        assert_eq!(Some(candidates[0].mv), objective.best_move);
        assert_eq!(candidates[0].score, objective.score);
        assert_eq!(analysis_position, Position::startpos());
        assert_eq!(objective_position, Position::startpos());
    }

    #[test]
    fn zero_depth_or_capacity_does_no_root_analysis_work() {
        let mut position = Position::startpos();
        let original = position.clone();
        let mut searcher = Searcher::with_tt_entries(64);

        assert!(
            searcher
                .analyze_root_candidates(&mut position, 0, 4)
                .is_empty()
        );
        assert!(
            searcher
                .analyze_root_candidates(&mut position, 2, 0)
                .is_empty()
        );
        assert_eq!(position, original);
    }
}
