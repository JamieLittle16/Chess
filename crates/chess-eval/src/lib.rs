//! Transparent classical evaluation used as the permanent reference baseline.
//!
//! This crate intentionally starts with material only. Search improvements and learned evaluators
//! can therefore be measured against a tiny evaluator whose behaviour is easy to inspect.

use chess_core::{Color, PieceKind, Position};

/// Conventional centipawn-like material values used by the reference evaluator.
pub const PIECE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

/// Return the material owned by one side in centipawn-like units.
#[must_use]
pub fn material(position: &Position, color: Color) -> i32 {
    PieceKind::ALL
        .into_iter()
        .map(|kind| position.pieces(color, kind).count() as i32 * PIECE_VALUES[kind.index()])
        .sum()
}

/// Evaluate a position from the side-to-move perspective.
///
/// Positive values favour the player to move; negative values favour their opponent. This makes
/// the evaluator directly compatible with negamax and keeps colour handling out of search.
#[must_use]
pub fn evaluate(position: &Position) -> i32 {
    let white_minus_black = material(position, Color::White) - material(position, Color::Black);
    match position.side_to_move() {
        Color::White => white_minus_black,
        Color::Black => -white_minus_black,
    }
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::evaluate;

    #[test]
    fn starting_position_is_materially_equal() {
        assert_eq!(evaluate(&Position::startpos()), 0);
    }

    #[test]
    fn score_is_from_side_to_move_perspective() {
        let white = Position::from_fen("7k/8/8/8/8/8/8/Q6K w - - 0 1").expect("valid FEN");
        let black = Position::from_fen("7k/8/8/8/8/8/8/Q6K b - - 0 1").expect("valid FEN");
        assert_eq!(evaluate(&white), 900);
        assert_eq!(evaluate(&black), -900);
    }
}
