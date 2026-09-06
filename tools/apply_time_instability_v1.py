#!/usr/bin/env python3
"""Apply the first instability-aware soft time-management experiment."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(
    search,
    '''pub trait SearchControl {
    #[must_use]
    fn should_stop(&self, nodes: u64) -> bool;
}''',
    '''pub trait SearchControl {
    #[must_use]
    fn should_stop(&self, nodes: u64) -> bool;

    /// Decide whether another iterative-deepening pass should begin after a completed root result.
    /// The default keeps depth/node-only and deterministic reference searches unchanged.
    #[must_use]
    fn should_start_next_iteration(&self, _completed: SearchResult) -> bool {
        true
    }
}''',
    "search-control iteration hook",
)
search = replace_once(
    search,
    '''                Some(mut result) => {
                    result.nodes = self.nodes;
                    result.tt_hits = self.tt_hits;
                    last_completed = Some(result);
                }''',
    '''                Some(mut result) => {
                    result.nodes = self.nodes;
                    result.tt_hits = self.tt_hits;
                    last_completed = Some(result);
                    if depth < max_depth && !control.should_start_next_iteration(result) {
                        #[cfg(debug_assertions)]
                        debug_assert_eq!(*position, root);
                        return SearchOutcome {
                            result,
                            stopped: true,
                        };
                    }
                }''',
    "iterative soft-stop hook",
)
search_path.write_text(search)

engine_path = Path("crates/chess-engine/src/lib.rs")
engine = engine_path.read_text()
engine = replace_once(
    engine,
    '''use std::{
    sync::{''',
    '''use std::{
    cell::Cell,
    sync::{''',
    "Cell import",
)
engine = replace_once(
    engine,
    '''        let deadline = limits
            .movetime
            .and_then(|duration| Instant::now().checked_add(duration));
        let control = EngineControl {
            stop,
            max_nodes: limits.max_nodes,
            deadline,
        };''',
    '''        let started_at = Instant::now();
        let deadline = limits
            .movetime
            .and_then(|duration| started_at.checked_add(duration));
        let soft_deadline = limits
            .movetime
            .and_then(|duration| started_at.checked_add(duration.mul_f64(0.70)));
        let control = EngineControl {
            stop,
            max_nodes: limits.max_nodes,
            deadline,
            soft_deadline,
            previous_best_move: Cell::new(None),
            previous_score: Cell::new(None),
        };''',
    "engine adaptive-control construction",
)
engine = replace_once(
    engine,
    '''struct EngineControl<'a> {
    stop: &'a StopToken,
    max_nodes: Option<u64>,
    deadline: Option<Instant>,
}''',
    '''struct EngineControl<'a> {
    stop: &'a StopToken,
    max_nodes: Option<u64>,
    deadline: Option<Instant>,
    soft_deadline: Option<Instant>,
    previous_best_move: Cell<Option<ChessMove>>,
    previous_score: Cell<Option<i32>>,
}''',
    "engine-control state",
)
engine = replace_once(
    engine,
    '''impl SearchControl for EngineControl<'_> {
    fn should_stop(&self, nodes: u64) -> bool {
        self.stop.is_stopped()
            || self.max_nodes.is_some_and(|limit| nodes >= limit)
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }
}''',
    '''impl SearchControl for EngineControl<'_> {
    fn should_stop(&self, nodes: u64) -> bool {
        self.stop.is_stopped()
            || self.max_nodes.is_some_and(|limit| nodes >= limit)
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }

    fn should_start_next_iteration(&self, completed: SearchResult) -> bool {
        let now = Instant::now();
        if self.stop.is_stopped()
            || self.deadline.is_some_and(|deadline| now >= deadline)
        {
            return false;
        }

        let previous_best_move = self.previous_best_move.replace(completed.best_move);
        let previous_score = self.previous_score.replace(Some(completed.score));

        let Some(soft_deadline) = self.soft_deadline else {
            return true;
        };
        if now < soft_deadline {
            return true;
        }

        // After 70% of the hard budget, bank time when the principal root decision is stable.
        // A changed best move or a >20 cp score swing keeps searching up to the existing hard limit.
        match (previous_best_move, previous_score) {
            (Some(previous_best_move), Some(previous_score)) => {
                Some(previous_best_move) != completed.best_move
                    || previous_score.abs_diff(completed.score) > 20
            }
            _ => true,
        }
    }
}''',
    "instability-aware control",
)
engine_path.write_text(engine)
