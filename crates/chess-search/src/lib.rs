//! Classical reference search.
//!
//! The first implementation is deliberately small: fixed-depth negamax with alpha-beta pruning
//! over the reversible `chess-core` state machine. It is a correctness and strength baseline, not
//! the final search architecture.

use chess_core::{ChessMove, Position, generate_legal_moves_mut};
use chess_eval::evaluate;

/// Scores at or above this range encode forced mate rather than static evaluation.
pub const MATE_SCORE: i32 = 30_000;
const INFINITY: i32 = 32_000;

/// Result of one deterministic fixed-depth reference search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchResult {
    pub best_move: Option<ChessMove>,
    pub score: i32,
    pub depth: u8,
    pub nodes: u64,
}

/// Search a position to an exact nominal depth.
///
/// The public immutable boundary clones the position once. Recursive search then uses make/unmake
/// exclusively; it never clones a position per child.
#[must_use]
pub fn search(position: &Position, depth: u8) -> SearchResult {
    let mut working = position.clone();
    search_mut(&mut working, depth)
}

/// Search using a caller-owned mutable working position, restoring it exactly before returning.
#[must_use]
pub fn search_mut(position: &mut Position, depth: u8) -> SearchResult {
    let root = position.clone();
    let mut nodes = 1_u64;
    let moves = generate_legal_moves_mut(position);

    if moves.is_empty() {
        let score = terminal_score(position, 0);
        debug_assert_eq!(*position, root);
        return SearchResult {
            best_move: None,
            score,
            depth,
            nodes,
        };
    }

    if depth == 0 {
        let score = evaluate(position);
        debug_assert_eq!(*position, root);
        return SearchResult {
            best_move: None,
            score,
            depth,
            nodes,
        };
    }

    let mut best_move = None;
    let mut best_score = -INFINITY;
    let mut alpha = -INFINITY;

    for &mv in &moves {
        let undo = position.make_move(mv);
        let score = -negamax(position, depth - 1, -INFINITY, -alpha, 1, &mut nodes);
        position.unmake_move(mv, undo);

        if score > best_score {
            best_score = score;
            best_move = Some(mv);
        }
        alpha = alpha.max(score);
    }

    debug_assert_eq!(*position, root);
    SearchResult {
        best_move,
        score: best_score,
        depth,
        nodes,
    }
}

fn negamax(
    position: &mut Position,
    depth: u8,
    mut alpha: i32,
    beta: i32,
    ply: u16,
    nodes: &mut u64,
) -> i32 {
    *nodes = nodes.saturating_add(1);

    let moves = generate_legal_moves_mut(position);
    if moves.is_empty() {
        return terminal_score(position, ply);
    }
    if depth == 0 {
        return evaluate(position);
    }

    let mut best = -INFINITY;
    for &mv in &moves {
        let undo = position.make_move(mv);
        let score = -negamax(position, depth - 1, -beta, -alpha, ply + 1, nodes);
        position.unmake_move(mv, undo);

        best = best.max(score);
        alpha = alpha.max(score);
        if alpha >= beta {
            break;
        }
    }
    best
}

fn terminal_score(position: &Position, ply: u16) -> i32 {
    if position.is_in_check(position.side_to_move()) {
        -MATE_SCORE + i32::from(ply)
    } else {
        0
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position};

    use super::{MATE_SCORE, search, search_mut};

    #[test]
    fn search_returns_a_legal_starting_move_without_mutating_root() {
        let root = Position::startpos();
        let legal = root.legal_moves();
        let result = search(&root, 2);
        assert!(
            result
                .best_move
                .is_some_and(|mv| legal.as_slice().contains(&mv))
        );
        assert!(result.nodes > 1);
        assert_eq!(root, Position::startpos());
    }

    #[test]
    fn mutable_search_restores_the_position_exactly() {
        let mut position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        let root = position.clone();
        let _ = search_mut(&mut position, 2);
        assert_eq!(position, root);
    }

    #[test]
    fn finds_a_mate_in_one() {
        let root = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1").expect("valid FEN");
        let result = search(&root, 1);
        assert!(result.score >= MATE_SCORE - 1);

        let mut child = root.clone();
        let mv = result.best_move.expect("mate has a best move");
        let _undo = child.make_move(mv);
        assert!(child.legal_moves().is_empty());
        assert!(child.is_in_check(Color::Black));
    }

    #[test]
    fn stalemate_is_zero() {
        let root = Position::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1").expect("valid FEN");
        let result = search(&root, 3);
        assert_eq!(result.best_move, None);
        assert_eq!(result.score, 0);
    }
}
