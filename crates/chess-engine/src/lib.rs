//! Stateful engine orchestration above the replaceable chess/search layers.
//!
//! `Engine` owns the current game position and a reusable searcher. Protocols and frontends should
//! depend on this crate rather than reaching into search internals directly.

use chess_core::{ChessMove, Position};
use chess_search::Searcher;
pub use chess_search::{MATE_SCORE, SearchResult};

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
}

impl Default for Engine {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{ChessMove, MoveKind, Square};

    use super::Engine;

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
}
