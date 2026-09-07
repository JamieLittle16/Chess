#!/usr/bin/env python3
"""Apply conservative root aspiration windows over accepted production search."""
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
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;",
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;\nconst ASPIRATION_START_DEPTH: u8 = 4;\nconst ASPIRATION_INITIAL_DELTA: i32 = 50;",
    "aspiration constants",
)

text = replace_once(
    text,
    '''        let result = self
            .search_root(position, prior_history, depth, &NeverStop)
            .expect("NeverStop cannot interrupt search");''',
    '''        let result = self
            .search_root(
                position,
                prior_history,
                depth,
                -INFINITY,
                INFINITY,
                &NeverStop,
            )
            .expect("NeverStop cannot interrupt search");''',
    "full-window direct search",
)

text = replace_once(
    text,
    '''        let mut last_completed = None;

        for depth in 1..=max_depth {
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
    '''        let mut last_completed: Option<SearchResult> = None;

        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            let aspiration_center = last_completed
                .map(|result| result.score)
                .filter(|score| depth >= ASPIRATION_START_DEPTH && score.abs() < MATE_TT_THRESHOLD);
            let center = aspiration_center.unwrap_or(0);
            let mut delta = ASPIRATION_INITIAL_DELTA;
            let mut alpha = aspiration_center
                .map_or(-INFINITY, |score| score.saturating_sub(delta).max(-INFINITY));
            let mut beta = aspiration_center
                .map_or(INFINITY, |score| score.saturating_add(delta).min(INFINITY));

            loop {
                match self.search_root(position, prior_history, depth, alpha, beta, control) {
                    Some(result) if result.score <= alpha && alpha > -INFINITY => {
                        delta = delta.saturating_mul(2).min(INFINITY);
                        alpha = center.saturating_sub(delta).max(-INFINITY);
                    }
                    Some(result) if result.score >= beta && beta < INFINITY => {
                        delta = delta.saturating_mul(2).min(INFINITY);
                        beta = center.saturating_add(delta).min(INFINITY);
                    }
                    Some(mut result) => {
                        result.nodes = self.nodes;
                        result.tt_hits = self.tt_hits;
                        last_completed = Some(result);
                        break;
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
            }
        }''',
    "iterative aspiration loop",
)

text = replace_once(
    text,
    '''    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {''',
    '''    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        mut alpha: i32,
        beta: i32,
        control: &C,
    ) -> Option<SearchResult> {
        debug_assert!(alpha < beta);''',
    "root window signature",
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
    "root alpha initialization",
)

text = replace_once(
    text,
    '''                    depth - 1,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    control,
                )''',
    '''                    depth - 1,
                    -beta,
                    -alpha,
                    1,
                    1,
                    control,
                )''',
    "first root move aspiration window",
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
    '''                    Some(probe_child) if -probe_child > alpha => self.negamax(
                        position,
                        prior_history,
                        depth - 1,
                        -beta,
                        -alpha,
                        1,
                        1,
                        control,
                    ),''',
    "later root full probe window",
)

text = replace_once(
    text,
    '''            if score > best_score {
                best_score = score;
                best_move = Some(mv);
            }
            alpha = alpha.max(score);
        }

        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            Bound::Exact,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))''',
    '''            if score > best_score {
                best_score = score;
                best_move = Some(mv);
            }
            alpha = alpha.max(score);
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
    "root bound and cutoff",
)

text = replace_once(
    text,
    '''    #[test]
    fn cached_root_result_cannot_bypass_stop_control() {''',
    '''    #[test]
    fn bounded_root_search_fails_soft_and_restores_position() {
        let mut root = Position::startpos();
        let original = root.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };

        let fail_high = searcher
            .search_root(&mut root, &[], 3, -500, -400, &super::NeverStop)
            .expect("uncontrolled root search completes");
        assert!(fail_high.score >= -400);
        assert_eq!(root, original);

        let fail_low = searcher
            .search_root(&mut root, &[], 3, 400, 500, &super::NeverStop)
            .expect("uncontrolled root search completes");
        assert!(fail_low.score <= 400);
        assert_eq!(root, original);
    }

    #[test]
    fn cached_root_result_cannot_bypass_stop_control() {''',
    "bounded root regression",
)

path.write_text(text)
