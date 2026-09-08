use chess_core::{Color, PieceKind, Position};

const TABLE_SIZE: usize = 1 << 13;
const TABLE_MASK: usize = TABLE_SIZE - 1;
const CORRECTION_LIMIT: i32 = 320;
const MAX_UPDATE: i32 = 96;

const WHITE_SALT: u64 = 0x9e37_79b9_7f4a_7c15;
const BLACK_SALT: u64 = 0xbf58_476d_1ce4_e5b9;
const PAWN_SALT: u64 = 0x94d0_49bb_1331_11eb;
const KNIGHT_SALT: u64 = 0xd6e8_feb8_6659_fd93;
const BISHOP_SALT: u64 = 0xa076_1d64_78bd_642f;
const ROOK_SALT: u64 = 0xe703_7ed1_a0b4_28db;
const QUEEN_SALT: u64 = 0x8ebc_6af0_9c88_c6e3;
const KING_SALT: u64 = 0x5899_65cc_7537_4cc3;

/// Game-local residual model layered on top of the mature learned evaluator.
///
/// The three independent tables deliberately generalise along different structural axes instead of
/// asking one pawn hash to explain every static-evaluation error. Entries are centipawn residuals;
/// lookup is three indexed i16 loads and a small weighted blend. `Engine::new_game` reconstructs the
/// searcher, so state may persist across moves inside one game without leaking between games.
pub(super) struct MultiContextCorrectionHistory {
    pawn: Box<[i16]>,
    minor: Box<[i16]>,
    heavy_king: Box<[i16]>,
}

impl MultiContextCorrectionHistory {
    #[must_use]
    pub(super) fn new() -> Self {
        let entries = 2 * TABLE_SIZE;
        Self {
            pawn: vec![0; entries].into_boxed_slice(),
            minor: vec![0; entries].into_boxed_slice(),
            heavy_king: vec![0; entries].into_boxed_slice(),
        }
    }

    /// Return the blended centipawn residual for the current side to move.
    #[must_use]
    pub(super) fn correction(&self, position: &Position) -> i32 {
        let keys = keys(position);
        let pawn = i32::from(self.pawn[keys.pawn]);
        let minor = i32::from(self.minor[keys.minor]);
        let heavy_king = i32::from(self.heavy_king[keys.heavy_king]);
        (4 * pawn + 3 * minor + 3 * heavy_king) / 10
    }

    /// Learn a bounded residual from a trustworthy shallow searched result.
    ///
    /// The caller performs alpha-beta bound-direction checks before calling this method. Depth two
    /// and three receive progressively more confidence; larger residuals are clipped so a single
    /// tactical accident cannot poison a structural bucket. Gravity prevents saturation when a
    /// structure is encountered repeatedly during iterative deepening or later moves in the game.
    pub(super) fn update(&mut self, position: &Position, residual: i32, depth: u8) {
        let keys = keys(position);
        let confidence = i32::from(depth.clamp(2, 3));
        let residual = residual.clamp(-640, 640);
        let bonus = (residual * confidence / 12).clamp(-MAX_UPDATE, MAX_UPDATE);
        if bonus == 0 {
            return;
        }
        update_entry(&mut self.pawn[keys.pawn], bonus);
        update_entry(&mut self.minor[keys.minor], bonus);
        update_entry(&mut self.heavy_king[keys.heavy_king], bonus);
    }
}

#[derive(Clone, Copy)]
struct CorrectionKeys {
    pawn: usize,
    minor: usize,
    heavy_king: usize,
}

#[inline]
fn keys(position: &Position) -> CorrectionKeys {
    CorrectionKeys {
        pawn: side_index(position, pawn_hash(position)),
        minor: side_index(position, minor_hash(position)),
        heavy_king: side_index(position, heavy_king_hash(position)),
    }
}

#[inline]
fn side_index(position: &Position, hash: u64) -> usize {
    position.side_to_move().index() * TABLE_SIZE + (hash as usize & TABLE_MASK)
}

#[inline]
fn pawn_hash(position: &Position) -> u64 {
    piece_pair_hash(position, PieceKind::Pawn, PAWN_SALT)
}

#[inline]
fn minor_hash(position: &Position) -> u64 {
    piece_pair_hash(position, PieceKind::Knight, KNIGHT_SALT)
        ^ piece_pair_hash(position, PieceKind::Bishop, BISHOP_SALT).rotate_left(19)
}

#[inline]
fn heavy_king_hash(position: &Position) -> u64 {
    piece_pair_hash(position, PieceKind::Rook, ROOK_SALT)
        ^ piece_pair_hash(position, PieceKind::Queen, QUEEN_SALT).rotate_left(17)
        ^ piece_pair_hash(position, PieceKind::King, KING_SALT).rotate_right(13)
}

#[inline]
fn piece_pair_hash(position: &Position, kind: PieceKind, salt: u64) -> u64 {
    let white = position.pieces(Color::White, kind).raw();
    let black = position.pieces(Color::Black, kind).raw();
    let white = white.wrapping_mul(salt ^ WHITE_SALT);
    let black = black
        .wrapping_mul(salt.rotate_left(23) ^ BLACK_SALT)
        .rotate_left(29);
    avalanche(white ^ black ^ (white.rotate_right(11) & black.rotate_left(7)))
}

#[inline]
fn avalanche(mut value: u64) -> u64 {
    value ^= value >> 30;
    value = value.wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value ^= value >> 27;
    value = value.wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

fn update_entry(entry: &mut i16, requested_bonus: i32) {
    let bonus = requested_bonus.clamp(-MAX_UPDATE, MAX_UPDATE);
    let current = i32::from(*entry);
    let gravity = current * bonus.abs() / CORRECTION_LIMIT;
    let updated = (current + bonus - gravity).clamp(-CORRECTION_LIMIT, CORRECTION_LIMIT);
    *entry = updated as i16;
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::{CORRECTION_LIMIT, MultiContextCorrectionHistory};

    #[test]
    fn residual_moves_correction_in_supported_direction() {
        let position = Position::startpos();
        let mut history = MultiContextCorrectionHistory::new();
        assert_eq!(history.correction(&position), 0);
        history.update(&position, 240, 3);
        assert!(history.correction(&position) > 0);
        history.update(&position, -480, 3);
        assert!(history.correction(&position) < 80);
    }

    #[test]
    fn structural_channels_generalise_independently() {
        let trained = Position::from_fen(
            "4k2r/ppp2ppp/2n5/8/8/2N5/PPP2PPP/R3K3 w Q - 0 1",
        )
        .expect("valid FEN");
        let same_pawns_different_pieces = Position::from_fen(
            "3rk3/ppp2ppp/8/8/2n5/8/PPP2PPP/2N1K2R w K - 0 1",
        )
        .expect("valid FEN");
        let mut history = MultiContextCorrectionHistory::new();
        history.update(&trained, 320, 3);
        let exact = history.correction(&trained);
        let partial = history.correction(&same_pawns_different_pieces);
        assert!(exact > 0);
        assert!(partial > 0, "matching pawn structure should retain some signal");
        assert!(partial < exact, "other structural channels should remain independent");
    }

    #[test]
    fn side_to_move_uses_distinct_buckets() {
        let white = Position::from_fen(
            "4k3/ppp2ppp/8/8/8/8/PPP2PPP/4K3 w - - 0 1",
        )
        .expect("valid FEN");
        let black = Position::from_fen(
            "4k3/ppp2ppp/8/8/8/8/PPP2PPP/4K3 b - - 0 1",
        )
        .expect("valid FEN");
        let mut history = MultiContextCorrectionHistory::new();
        history.update(&white, 240, 3);
        assert!(history.correction(&white) > 0);
        assert_eq!(history.correction(&black), 0);
    }

    #[test]
    fn gravity_keeps_blended_correction_bounded() {
        let position = Position::startpos();
        let mut history = MultiContextCorrectionHistory::new();
        for _ in 0..20_000 {
            history.update(&position, 10_000, 3);
        }
        assert!(history.correction(&position) <= CORRECTION_LIMIT);
        for _ in 0..40_000 {
            history.update(&position, -10_000, 3);
        }
        assert!(history.correction(&position) >= -CORRECTION_LIMIT);
    }
}
