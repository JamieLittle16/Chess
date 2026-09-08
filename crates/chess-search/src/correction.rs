use chess_core::{Color, PieceKind, Position};

const PAWN_CORRECTION_BUCKETS: usize = 1 << 14;
const PAWN_CORRECTION_ENTRIES: usize = 2 * PAWN_CORRECTION_BUCKETS;
const CORRECTION_LIMIT: i32 = 384;

/// Search-local pawn-structure correction history.
///
/// This is deliberately smaller than modern multi-table correction systems. V14 first tests whether
/// the mechanism itself helps our shallow selective search: positions sharing a pawn structure and
/// side-to-move learn a bounded centipawn correction from earlier iterative-deepening search results.
pub(super) struct PawnCorrectionHistory {
    entries: Box<[i16]>,
}

impl PawnCorrectionHistory {
    #[must_use]
    pub(super) fn new() -> Self {
        Self {
            entries: vec![0; PAWN_CORRECTION_ENTRIES].into_boxed_slice(),
        }
    }

    pub(super) fn clear(&mut self) {
        self.entries.fill(0);
    }

    #[must_use]
    pub(super) fn corrected_eval(&self, position: &Position, raw_eval: i32) -> i32 {
        raw_eval.saturating_add(i32::from(self.entries[index(position)]))
    }

    /// Learn toward the observed search residual with a depth-weighted bounded EMA.
    ///
    /// The table stores correction directly in centipawns. Shallow nodes move slowly; deeper nodes
    /// are trusted more, but one observation can never replace the table outright.
    pub(super) fn update(
        &mut self,
        position: &Position,
        raw_eval: i32,
        searched_score: i32,
        depth: u8,
    ) {
        let target = searched_score
            .saturating_sub(raw_eval)
            .clamp(-CORRECTION_LIMIT, CORRECTION_LIMIT);
        let slot = &mut self.entries[index(position)];
        let current = i32::from(*slot);
        let weight = (16 + 10 * i32::from(depth)).min(112);
        let learned = current + (target - current) * weight / 256;
        *slot = learned.clamp(-CORRECTION_LIMIT, CORRECTION_LIMIT) as i16;
    }
}

#[inline]
fn index(position: &Position) -> usize {
    let white = position.pieces(Color::White, PieceKind::Pawn).raw();
    let black = position.pieces(Color::Black, PieceKind::Pawn).raw();
    let mixed = mix64(
        white
            ^ black.rotate_left(29)
            ^ black.wrapping_mul(0x9E37_79B9_7F4A_7C15),
    );
    position.side_to_move().index() * PAWN_CORRECTION_BUCKETS
        + (mixed as usize & (PAWN_CORRECTION_BUCKETS - 1))
}

#[inline]
fn mix64(mut value: u64) -> u64 {
    value ^= value >> 30;
    value = value.wrapping_mul(0xBF58_476D_1CE4_E5B9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94D0_49BB_1331_11EB);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::{CORRECTION_LIMIT, PawnCorrectionHistory, index};

    #[test]
    fn correction_learns_in_the_direction_of_search_residual() {
        let position = Position::startpos();
        let mut correction = PawnCorrectionHistory::new();
        assert_eq!(correction.corrected_eval(&position, 25), 25);

        correction.update(&position, 25, 225, 6);
        let corrected = correction.corrected_eval(&position, 25);
        assert!(corrected > 25);
        assert!(corrected < 225);
    }

    #[test]
    fn correction_is_side_specific() {
        let white = Position::startpos();
        let black = Position::from_fen(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 1",
        )
        .expect("valid FEN");
        assert_ne!(index(&white), index(&black));
    }

    #[test]
    fn different_pawn_structures_normally_select_different_buckets() {
        let start = Position::startpos();
        let advanced = Position::from_fen(
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1",
        )
        .expect("valid FEN");
        assert_ne!(index(&start), index(&advanced));
    }

    #[test]
    fn repeated_updates_stay_bounded() {
        let position = Position::startpos();
        let mut correction = PawnCorrectionHistory::new();
        for _ in 0..10_000 {
            correction.update(&position, 0, 10_000, 64);
        }
        let corrected = correction.corrected_eval(&position, 0);
        assert!((0..=CORRECTION_LIMIT).contains(&corrected));

        correction.clear();
        assert_eq!(correction.corrected_eval(&position, 0), 0);
    }
}
