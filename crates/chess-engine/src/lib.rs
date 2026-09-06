//! Stateful engine orchestration above the replaceable chess/search layers.
//!
//! `Engine` owns the current game position and a reusable searcher. Protocols and frontends should
//! depend on this crate rather than reaching into search internals directly.

use std::{
    sync::{
        Arc,
        atomic::{AtomicBool, Ordering},
    },
    time::{Duration, Instant},
};

use chess_core::{ChessMove, Position};
pub use chess_search::{MATE_SCORE, SearchOutcome, SearchResult};
use chess_search::{SearchControl, Searcher};

/// Cloneable cooperative cancellation signal for one running search.
#[derive(Clone, Debug, Default)]
pub struct StopToken {
    stopped: Arc<AtomicBool>,
}

impl StopToken {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    pub fn stop(&self) {
        self.stopped.store(true, Ordering::Relaxed);
    }

    pub fn reset(&self) {
        self.stopped.store(false, Ordering::Relaxed);
    }

    #[must_use]
    pub fn is_stopped(&self) -> bool {
        self.stopped.load(Ordering::Relaxed)
    }
}

/// Clock information for the side whose move is being searched.
///
/// This type is protocol-neutral. A UCI adapter, website, or match harness may all map their own
/// clock representation into the same engine-owned budgeting policy.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ClockState {
    pub remaining: Duration,
    pub increment: Duration,
    pub moves_to_go: Option<u32>,
}

impl ClockState {
    #[must_use]
    pub const fn new(
        remaining: Duration,
        increment: Duration,
        moves_to_go: Option<u32>,
    ) -> Self {
        Self {
            remaining,
            increment,
            moves_to_go,
        }
    }

    /// Convert a game clock into the current conservative single-move hard budget.
    ///
    /// M3 intentionally uses one transparent budget rather than pretending to have mature time
    /// management. Five percent of the remaining clock is reserved, the spendable time is divided
    /// across `moves_to_go` (or 30 moves by default), and 75% of one increment is added. The final
    /// budget can never exceed the spendable clock after reserve.
    #[must_use]
    pub fn allocated_movetime(self) -> Duration {
        let remaining_ms = self.remaining.as_millis();
        if remaining_ms == 0 {
            return Duration::ZERO;
        }

        let reserve_ms = (remaining_ms / 20).max(1).min(remaining_ms / 2);
        let spendable_ms = remaining_ms - reserve_ms;
        if spendable_ms == 0 {
            return Duration::ZERO;
        }

        let expected_moves = u128::from(self.moves_to_go.unwrap_or(30).clamp(1, 60));
        let base_ms = spendable_ms / expected_moves;
        let increment_share_ms = self.increment.as_millis().saturating_mul(3) / 4;
        let budget_ms = base_ms
            .saturating_add(increment_share_ms)
            .max(1)
            .min(spendable_ms);

        Duration::from_millis(u64::try_from(budget_ms).unwrap_or(u64::MAX))
    }
}

/// Search limits owned by orchestration rather than chess/search semantics.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchLimits {
    pub max_depth: u8,
    pub max_nodes: Option<u64>,
    pub movetime: Option<Duration>,
}

impl SearchLimits {
    #[must_use]
    pub const fn depth(max_depth: u8) -> Self {
        Self {
            max_depth,
            max_nodes: None,
            movetime: None,
        }
    }

    #[must_use]
    pub const fn nodes(max_depth: u8, max_nodes: u64) -> Self {
        Self {
            max_depth,
            max_nodes: Some(max_nodes),
            movetime: None,
        }
    }

    #[must_use]
    pub const fn movetime(max_depth: u8, movetime: Duration) -> Self {
        Self {
            max_depth,
            max_nodes: None,
            movetime: Some(movetime),
        }
    }

    /// Build concrete search limits from a game clock using engine-owned budgeting policy.
    #[must_use]
    pub fn clock(max_depth: u8, clock: ClockState) -> Self {
        Self::movetime(max_depth, clock.allocated_movetime())
    }
}

/// Persistent engine state shared by protocol/deployment frontends.
pub struct Engine {
    position: Position,
    searcher: Searcher,
}

impl Engine {
    #[must_use]
    pub fn new() -> Self {
        Self {
            position: Position::startpos(),
            searcher: Searcher::default(),
        }
    }

    #[must_use]
    pub const fn position(&self) -> &Position {
        &self.position
    }

    /// Replace the game position without changing search configuration.
    pub fn set_position(&mut self, position: Position) {
        self.position = position;
    }

    /// Start a fresh game and discard search memory from the previous game.
    pub fn new_game(&mut self) {
        self.position = Position::startpos();
        self.searcher = Searcher::default();
    }

    /// Apply one move only when it is legal in the current position.
    ///
    /// This boundary is deliberately defensive because protocol/UI callers may supply arbitrary
    /// coordinates. Core search itself calls `Position::make_move` only with generated moves.
    pub fn apply_move(&mut self, mv: ChessMove) -> bool {
        let legal = self.position.legal_moves();
        if !legal.as_slice().contains(&mv) {
            return false;
        }
        let _undo = self.position.make_move(mv);
        true
    }

    /// Iteratively search to `max_depth` while leaving the game position unchanged.
    #[must_use]
    pub fn search_depth(&mut self, max_depth: u8) -> SearchResult {
        self.searcher
            .iterative_deepening(&mut self.position, max_depth)
    }

    /// Search under cooperative depth/node/time limits.
    ///
    /// The result always contains a legal fallback when legal moves exist, even if the stop signal
    /// or deadline fires before depth one completes.
    #[must_use]
    pub fn search_with_limits(&mut self, limits: SearchLimits, stop: &StopToken) -> SearchOutcome {
        let deadline = limits
            .movetime
            .and_then(|duration| Instant::now().checked_add(duration));
        let control = EngineControl {
            stop,
            max_nodes: limits.max_nodes,
            deadline,
        };
        self.searcher
            .iterative_deepening_controlled(&mut self.position, limits.max_depth, &control)
    }
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

struct EngineControl<'a> {
    stop: &'a StopToken,
    max_nodes: Option<u64>,
    deadline: Option<Instant>,
}

impl SearchControl for EngineControl<'_> {
    fn should_stop(&self, nodes: u64) -> bool {
        self.stop.is_stopped()
            || self.max_nodes.is_some_and(|limit| nodes >= limit)
            || self
                .deadline
                .is_some_and(|deadline| Instant::now() >= deadline)
    }
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use chess_core::{ChessMove, MoveKind, Square};

    use super::{ClockState, Engine, SearchLimits, StopToken};

    #[test]
    fn illegal_external_move_is_rejected_without_mutation() {
        let mut engine = Engine::new();
        let root = engine.position().clone();
        let e2 = Square::from_file_rank(4, 1).expect("e2");
        let e5 = Square::from_file_rank(4, 4).expect("e5");
        let illegal = ChessMove::new(e2, e5, MoveKind::Quiet);
        assert!(!engine.apply_move(illegal));
        assert_eq!(engine.position(), &root);
    }

    #[test]
    fn legal_external_move_advances_the_game() {
        let mut engine = Engine::new();
        let e2 = Square::from_file_rank(4, 1).expect("e2");
        let e4 = Square::from_file_rank(4, 3).expect("e4");
        let mv = engine
            .position()
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.from() == e2 && mv.to() == e4)
            .expect("e2e4 is legal");
        assert!(engine.apply_move(mv));
        assert_ne!(engine.position(), &chess_core::Position::startpos());
    }

    #[test]
    fn search_does_not_advance_game_position() {
        let mut engine = Engine::new();
        let root = engine.position().clone();
        let legal = root.legal_moves();
        let result = engine.search_depth(2);
        assert!(
            result
                .best_move
                .is_some_and(|mv| legal.as_slice().contains(&mv))
        );
        assert_eq!(engine.position(), &root);
    }

    #[test]
    fn node_limit_stops_cooperatively_and_restores_root() {
        let mut engine = Engine::new();
        let root = engine.position().clone();
        let legal = root.legal_moves();
        let outcome = engine.search_with_limits(SearchLimits::nodes(32, 20), &StopToken::new());
        assert!(outcome.stopped);
        assert!(outcome.result.nodes >= 20);
        assert!(
            outcome
                .result
                .best_move
                .is_some_and(|mv| legal.as_slice().contains(&mv))
        );
        assert_eq!(engine.position(), &root);
    }

    #[test]
    fn pre_stopped_token_returns_legal_fallback() {
        let mut engine = Engine::new();
        let root = engine.position().clone();
        let legal = root.legal_moves();
        let stop = StopToken::new();
        stop.stop();
        let outcome = engine.search_with_limits(SearchLimits::depth(32), &stop);
        assert!(outcome.stopped);
        assert_eq!(outcome.result.depth, 0);
        assert!(
            outcome
                .result
                .best_move
                .is_some_and(|mv| legal.as_slice().contains(&mv))
        );
        assert_eq!(engine.position(), &root);
    }

    #[test]
    fn expired_movetime_returns_without_corrupting_position() {
        let mut engine = Engine::new();
        let root = engine.position().clone();
        let outcome = engine.search_with_limits(
            SearchLimits::movetime(32, Duration::ZERO),
            &StopToken::new(),
        );
        assert!(outcome.stopped);
        assert_eq!(engine.position(), &root);
    }

    #[test]
    fn clock_budget_policy_is_conservative_and_pinned() {
        let no_increment = ClockState::new(Duration::from_secs(60), Duration::ZERO, None);
        assert_eq!(no_increment.allocated_movetime(), Duration::from_millis(1_900));

        let increment = ClockState::new(
            Duration::from_secs(60),
            Duration::from_secs(1),
            None,
        );
        assert_eq!(increment.allocated_movetime(), Duration::from_millis(2_650));

        let ten_moves = ClockState::new(Duration::from_secs(60), Duration::ZERO, Some(10));
        assert_eq!(ten_moves.allocated_movetime(), Duration::from_millis(5_700));
    }

    #[test]
    fn clock_budget_never_spends_the_reserved_tail() {
        let clock = ClockState::new(
            Duration::from_millis(100),
            Duration::from_secs(60),
            Some(1),
        );
        assert_eq!(clock.allocated_movetime(), Duration::from_millis(95));
        assert!(clock.allocated_movetime() < clock.remaining);
        assert_eq!(
            ClockState::new(Duration::ZERO, Duration::ZERO, None).allocated_movetime(),
            Duration::ZERO
        );
    }
}
