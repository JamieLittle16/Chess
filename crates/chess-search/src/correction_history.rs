use chess_core::{Color, PieceKind, Position};

const PAWN_CORRECTION_SIZE: usize = 1 << 14;
const CORRECTION_LIMIT: i32 = 384;
const MAX_UPDATE: i32 = 128;
const WHITE_MIX: u64 = 0x9e37_79b9_7f4a_7c15;
const BLACK_MIX: u64 = 0xbf58_476d_1ce4_e5b9;

/// Small search-local correction table keyed by pawn structure and side to move.
///
/// Pawn structure is deliberately reconstructed from the two cached pawn bitboards rather than
/// adding another incrementally maintained key to `Position`: a lookup costs two loads, two cheap
/// mixes and one indexed i16 read, while ordinary make/unmake remains completely untouched.
#[allow(dead_code)]
pub(super) struct PawnCorrectionHistory {
    entries: Box<[i16]>,
}

#[allow(dead_code)]
impl PawnCorrectionHistory {
    #[must_use]
    pub(super) fn new() -> Self {
        Self {
            entries: vec![0; 2 * PAWN_CORRECTION_SIZE].into_boxed_slice(),
        }
    }

    pub(super) fn clear(&mut self) {
        self.entries.fill(0);
    }

    #[must_use]
    pub(super) fn correction(&self, position: &Position) -> i32 {
        i32::from(self.entries[index(position)])
    }

    /// Learn a bounded centipawn correction from a searched score.
    ///
    /// The caller is responsible for updating only when the alpha-beta bound supports the direction
    /// of the residual. `depth` controls confidence, while the gravity term prevents saturation from
    /// one recurring structure.
    pub(super) fn update(&mut self, position: &Position, residual: i32, depth: u8) {
        let confidence = i32::from(depth).clamp(1, 4);
        let bonus = (residual * confidence / 4).clamp(-MAX_UPDATE, MAX_UPDATE);
        let slot = &mut self.entries[index(position)];
        let current = i32::from(*slot);
        let gravity = current * bonus.abs() / CORRECTION_LIMIT;
        *slot = (current + bonus - gravity)
            .clamp(-CORRECTION_LIMIT, CORRECTION_LIMIT) as i16;
    }
}

#[inline]
fn index(position: &Position) -> usize {
    let white = position.pieces(Color::White, PieceKind::Pawn).raw();
    let black = position.pieces(Color::Black, PieceKind::Pawn).raw();
    let mixed = white
        .wrapping_mul(WHITE_MIX)
        ^ black.wrapping_mul(BLACK_MIX).rotate_left(23)
        ^ (white ^ black).rotate_right(17);
    position.side_to_move().index() * PAWN_CORRECTION_SIZE
        + (mixed as usize & (PAWN_CORRECTION_SIZE - 1))
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::{CORRECTION_LIMIT, PawnCorrectionHistory};

    #[test]
    fn repeated_supported_residual_moves_correction_in_expected_direction() {
        let position = Position::startpos();
        let mut history = PawnCorrectionHistory::new();
        assert_eq!(history.correction(&position), 0);
        history.update(&position, 120, 4);
        assert!(history.correction(&position) > 0);
        history.update(&position, -240, 4);
        assert!(history.correction(&position) < 120);
    }

    #[test]
    fn correction_is_shared_by_piece_rearrangements_with_same_pawns_and_side() {
        let a = Position::from_fen("4k3/ppp5/8/8/8/8/PPP1N3/4K3 w - - 0 1").expect("valid FEN");
        let b = Position::from_fen("4k3/ppp5/8/8/8/2N5/PPP5/4K3 w - - 0 1").expect("valid FEN");
        let mut history = PawnCorrectionHistory::new();
        history.update(&a, 160, 4);
        assert_eq!(history.correction(&a), history.correction(&b));
    }

    #[test]
    fn gravity_bounds_extreme_repetition() {
        let position = Position::startpos();
        let mut history = PawnCorrectionHistory::new();
        for _ in 0..10_000 {
            history.update(&position, 10_000, 4);
        }
        assert!(history.correction(&position) <= CORRECTION_LIMIT);
        for _ in 0..20_000 {
            history.update(&position, -10_000, 4);
        }
        assert!(history.correction(&position) >= -CORRECTION_LIMIT);
    }

    #[test]
    fn clear_removes_learned_state() {
        let position = Position::startpos();
        let mut history = PawnCorrectionHistory::new();
        history.update(&position, 100, 4);
        assert_ne!(history.correction(&position), 0);
        history.clear();
        assert_eq!(history.correction(&position), 0);
    }
}
