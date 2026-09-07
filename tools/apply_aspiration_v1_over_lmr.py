#!/usr/bin/env python3
"""Apply bound-correct iterative-deepening aspiration windows over accepted LMR v3."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    "const MAX_SEARCH_PLY: usize = 256;",
    "const MAX_SEARCH_PLY: usize = 256;\nconst ASPIRATION_INITIAL_DELTA: i32 = 50;",
    "aspiration constant",
)

text = replace_once(
    text,
    '''        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            match self.search_root(position, prior_history, depth, control) {
                Some(mut result) => {
                    result.nodes = self.nodes;
                    result.tt_hits = self.tt_hits;
                    last_completed = Some(result);
                }
                None => {
                    let result = match last_completed {
                        Some(mut result) => {
                            result.nodes = self.nodes;
                            result.tt_hits = self.tt_hits;
                            result
                        }
                        None => self.fallback_result(position, prior_history),
                    };
                    #[cfg(debug_assertions)]
                    debug_assert_eq!(*position, root);
                    return SearchOutcome {
                        result,
                        stopped: true,
                    };
                }
            }
        }''',
    '''        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            let iteration = match last_completed {
                Some(previous) if previous.score.abs() < MATE_TT_THRESHOLD => self
                    .search_root_aspirated(
                        position,
                        prior_history,
                        depth,
                        previous.score,
                        control,
                    ),
                Some(_) | None => self.search_root(position, prior_history, depth, control),
            };
            match iteration {
                Some(mut result) => {
                    result.nodes = self.nodes;
                    result.tt_hits = self.tt_hits;
                    last_completed = Some(result);
                }
                None => {
                    let result = match last_completed {
                        Some(mut result) => {
                            result.nodes = self.nodes;
                            result.tt_hits = self.tt_hits;
                            result
                        }
                        None => self.fallback_result(position, prior_history),
                    };
                    #[cfg(debug_assertions)]
                    debug_assert_eq!(*position, root);
                    return SearchOutcome {
                        result,
                        stopped: true,
                    };
                }
            }
        }''',
    "iterative aspiration integration",
)

text = replace_once(
    text,
    '''    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {
        // Control must precede even an exact root TT hit; otherwise a cached result can make an''',
    '''    fn search_root_aspirated<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        centre: i32,
        control: &C,
    ) -> Option<SearchResult> {
        let mut delta = ASPIRATION_INITIAL_DELTA;
        loop {
            let alpha = centre.saturating_sub(delta).max(-INFINITY);
            let beta = centre.saturating_add(delta).min(INFINITY);
            let result = self.search_root_window(
                position,
                prior_history,
                depth,
                alpha,
                beta,
                control,
            )?;
            if (result.score > alpha && result.score < beta)
                || (alpha == -INFINITY && beta == INFINITY)
            {
                return Some(result);
            }

            // A failed aspiration probe is real root work. Count the retry root explicitly so
            // node accounting and cooperative stop checks remain conservative.
            self.nodes = self.nodes.saturating_add(1);
            delta = delta.saturating_mul(2).min(INFINITY);
        }
    }

    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {
        self.search_root_window(
            position,
            prior_history,
            depth,
            -INFINITY,
            INFINITY,
            control,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn search_root_window<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        mut alpha: i32,
        beta: i32,
        control: &C,
    ) -> Option<SearchResult> {
        // Control must precede even an exact root TT hit; otherwise a cached result can make an''',
    "root window helper",
)

text = replace_once(
    text,
    '''        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;
        let mut best_score = -INFINITY;
        let mut alpha = -INFINITY;
        self.path_keys[0] = repetition_key;''',
    '''        let hint = table_entry.and_then(|entry| entry.best_move);
        let alpha_original = alpha;
        let mut best_move = None;
        let mut best_score = -INFINITY;
        self.path_keys[0] = repetition_key;''',
    "root original alpha",
)

text = replace_once(
    text,
    '''                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    control,
                )''',
    '''                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    1,
                    1,
                    control,
                )''',
    "root first move window",
)

text = replace_once(
    text,
    '''                    Some(probe_child) if -probe_child > alpha => self.negamax(
                        position,
                        prior_history,
                        depth - 1,
                        -INFINITY,
                        -alpha,
                        1,
                        1,
                        control,
                    ),''',
    '''                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            depth - 1,
                            -beta,
                            -alpha,
                            1,
                            1,
                            control,
                        ),''',
    "root pvs verification window",
)

text = replace_once(
    text,
    '''            alpha = alpha.max(score);
        }

        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            Bound::Exact,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))''',
    '''            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }

        let bound = if best_score <= alpha_original {
            Bound::Upper
        } else if best_score >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };
        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            bound,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))''',
    "root bound storage",
)

text = replace_once(
    text,
    '''    #[test]
    fn controlled_search_stops_and_restores_position() {''',
    '''    #[test]
    fn narrow_root_failures_are_bounds_and_full_retry_recovers_exact_score() {
        let mut root = Position::startpos();
        let exact = search(&root, 3);

        let mut searcher = Searcher::default();
        searcher.nodes = 1;
        let fail_low = searcher
            .search_root_window(
                &mut root,
                &[],
                3,
                exact.score + 40,
                exact.score + 80,
                &super::NeverStop,
            )
            .expect("narrow root search completes");
        assert!(fail_low.score <= exact.score + 40);

        searcher.nodes = searcher.nodes.saturating_add(1);
        let recovered = searcher
            .search_root_window(
                &mut root,
                &[],
                3,
                -super::INFINITY,
                super::INFINITY,
                &super::NeverStop,
            )
            .expect("full retry completes");
        assert_eq!(recovered.score, exact.score);
        assert_eq!(root, Position::startpos());
    }

    #[test]
    fn controlled_search_stops_and_restores_position() {''',
    "aspiration bound test",
)

path.write_text(text)
