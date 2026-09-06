#!/usr/bin/env python3
"""Apply a conservative one-shot aspiration window around the previous root score."""
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
    "const MATE_TT_THRESHOLD: i32 = MATE_SCORE - 1_000;\nconst MAX_SEARCH_PLY: usize = 256;",
    "const MATE_TT_THRESHOLD: i32 = MATE_SCORE - 1_000;\nconst ASPIRATION_HALF_WINDOW: i32 = 50;\nconst MAX_SEARCH_PLY: usize = 256;",
    "aspiration constant",
)
text = replace_once(
    text,
    '''        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            match self.search_root(position, prior_history, depth, control) {''',
    '''        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            match self.search_iteration(
                position,
                prior_history,
                depth,
                last_completed,
                control,
            ) {''',
    "iterative aspiration dispatch",
)
needle = '''    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {
'''
replacement = '''    fn search_iteration<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        previous: Option<SearchResult>,
        control: &C,
    ) -> Option<SearchResult> {
        let Some(previous) = previous else {
            return self.search_root(position, prior_history, depth, control);
        };
        if depth <= 1 || previous.score.abs() >= MATE_TT_THRESHOLD {
            return self.search_root(position, prior_history, depth, control);
        }

        let alpha = previous
            .score
            .saturating_sub(ASPIRATION_HALF_WINDOW)
            .max(-INFINITY);
        let beta = previous
            .score
            .saturating_add(ASPIRATION_HALF_WINDOW)
            .min(INFINITY);
        let attempt = self.search_root_window(position, prior_history, depth, alpha, beta, control)?;
        if attempt.score > alpha && attempt.score < beta {
            return Some(attempt);
        }

        // A fail-low/high result is only a bound. Re-search the same depth with the ordinary full
        // root window before treating the iteration as complete.
        self.nodes = self.nodes.saturating_add(1);
        self.search_root(position, prior_history, depth, control)
    }

    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {
        self.search_root_window(position, prior_history, depth, -INFINITY, INFINITY, control)
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
'''
text = replace_once(text, needle, replacement, "root window split")
text = replace_once(
    text,
    '''        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;
        let mut best_score = -INFINITY;
        let mut alpha = -INFINITY;
        self.path_keys[0] = repetition_key;''',
    '''        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;
        let mut best_score = -INFINITY;
        let alpha_original = alpha;
        self.path_keys[0] = repetition_key;''',
    "root alpha input",
)
text = replace_once(
    text,
    '''                    depth - 1,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    control,
                )
            } else {
                // Later root moves first get a null-window probe.''',
    '''                    depth - 1,
                    -beta,
                    -alpha,
                    1,
                    1,
                    control,
                )
            } else {
                // Later root moves first get a null-window probe.''',
    "first root move aspiration window",
)
text = replace_once(
    text,
    '''                match probe {
                    Some(probe_child) if -probe_child > alpha => self.negamax(
                        position,
                        prior_history,
                        depth - 1,
                        -INFINITY,
                        -alpha,
                        1,
                        1,
                        control,
                    ),
                    probe => probe,
                }''',
    '''                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            depth - 1,
                            -beta,
                            -alpha,
                            1,
                            1,
                            control,
                        ),
                    probe => probe,
                }''',
    "later root move aspiration verification",
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
        Some(self.result(best_move, best_score, depth))
    }
''',
    '''            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }

        // Only an in-window result is exact. Fail-low/high aspiration results are deliberately not
        // stored as exact root entries; `search_iteration` immediately verifies them at full width.
        if best_score > alpha_original && best_score < beta {
            self.table.store(
                key,
                depth,
                score_to_tt(best_score, 0),
                Bound::Exact,
                best_move,
            );
        }
        Some(self.result(best_move, best_score, depth))
    }
''',
    "root fail bound handling",
)
path.write_text(text)
