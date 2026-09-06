use crate::{CastlingRights, Color, Piece, PieceKind, Position, Square};

const PIECE_SLOTS: usize = 12;
const SQUARES: usize = 64;
const ZOBRIST_SEED: u64 = 0x6a09_e667_f3bc_c909;

const PIECE_KEYS: [[u64; SQUARES]; PIECE_SLOTS] = build_piece_keys();
const SIDE_KEY: u64 = derived_key((PIECE_SLOTS * SQUARES) as u64);
const CASTLING_KEYS: [u64; 4] = build_castling_keys();
const EN_PASSANT_KEYS: [u64; SQUARES] = build_en_passant_keys();

/// Deterministic 64-bit position identity used by search caches.
///
/// The key covers piece placement, side to move, castling rights and the exact en-passant target.
/// Move clocks are deliberately excluded; draw-rule context must be handled separately by search.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
#[repr(transparent)]
pub struct ZobristKey(u64);

impl ZobristKey {
    pub const ZERO: Self = Self(0);

    #[must_use]
    pub const fn raw(self) -> u64 {
        self.0
    }

    pub(crate) fn toggle(&mut self, component: u64) {
        self.0 ^= component;
    }
}

pub(crate) fn piece_component(piece: Piece, square: Square) -> u64 {
    PIECE_KEYS[piece.slot()][square.index() as usize]
}

pub(crate) const fn side_component(color: Color) -> u64 {
    match color {
        Color::White => 0,
        Color::Black => SIDE_KEY,
    }
}

pub(crate) fn castling_component(rights: CastlingRights) -> u64 {
    let mut key = 0_u64;
    if rights.contains(CastlingRights::WHITE_KING) {
        key ^= CASTLING_KEYS[0];
    }
    if rights.contains(CastlingRights::WHITE_QUEEN) {
        key ^= CASTLING_KEYS[1];
    }
    if rights.contains(CastlingRights::BLACK_KING) {
        key ^= CASTLING_KEYS[2];
    }
    if rights.contains(CastlingRights::BLACK_QUEEN) {
        key ^= CASTLING_KEYS[3];
    }
    key
}

pub(crate) fn en_passant_component(square: Option<Square>) -> u64 {
    square.map_or(0, |square| EN_PASSANT_KEYS[square.index() as usize])
}

#[must_use]
pub(crate) fn recompute(position: &Position) -> ZobristKey {
    let mut key = ZobristKey::ZERO;
    for color in Color::ALL {
        for kind in PieceKind::ALL {
            for square in position.pieces(color, kind) {
                key.toggle(piece_component(Piece::new(color, kind), square));
            }
        }
    }
    key.toggle(side_component(position.side_to_move()));
    key.toggle(castling_component(position.castling_rights()));
    key.toggle(en_passant_component(position.en_passant()));
    key
}

const fn build_piece_keys() -> [[u64; SQUARES]; PIECE_SLOTS] {
    let mut keys = [[0_u64; SQUARES]; PIECE_SLOTS];
    let mut slot = 0_usize;
    while slot < PIECE_SLOTS {
        let mut square = 0_usize;
        while square < SQUARES {
            keys[slot][square] = derived_key((slot * SQUARES + square) as u64);
            square += 1;
        }
        slot += 1;
    }
    keys
}

const fn build_castling_keys() -> [u64; 4] {
    let base = (PIECE_SLOTS * SQUARES + 1) as u64;
    [
        derived_key(base),
        derived_key(base + 1),
        derived_key(base + 2),
        derived_key(base + 3),
    ]
}

const fn build_en_passant_keys() -> [u64; SQUARES] {
    let base = (PIECE_SLOTS * SQUARES + 5) as u64;
    let mut keys = [0_u64; SQUARES];
    let mut square = 0_usize;
    while square < SQUARES {
        keys[square] = derived_key(base + square as u64);
        square += 1;
    }
    keys
}

const fn derived_key(index: u64) -> u64 {
    splitmix64(ZOBRIST_SEED.wrapping_add(index.wrapping_mul(0x9e37_79b9_7f4a_7c15)))
}

const fn splitmix64(mut value: u64) -> u64 {
    value = value.wrapping_add(0x9e37_79b9_7f4a_7c15);
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[cfg(test)]
mod tests {
    use crate::Position;

    #[test]
    fn key_is_deterministic_and_ignores_move_clocks() {
        let a = Position::from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
            .expect("valid FEN");
        let b = Position::from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 73 42")
            .expect("valid FEN");
        assert_eq!(a.zobrist_key(), b.zobrist_key());
        assert_eq!(a.zobrist_key(), a.recomputed_zobrist_key());
    }

    #[test]
    fn search_relevant_state_changes_key() {
        let white = Position::from_fen("8/8/8/8/8/8/8/K6k w - - 0 1").expect("valid FEN");
        let black = Position::from_fen("8/8/8/8/8/8/8/K6k b - - 0 1").expect("valid FEN");
        let castling = Position::from_fen("4k3/8/8/8/8/8/8/4K2R w K - 0 1").expect("valid FEN");
        let no_castling = Position::from_fen("4k3/8/8/8/8/8/8/4K2R w - - 0 1").expect("valid FEN");
        assert_ne!(white.zobrist_key(), black.zobrist_key());
        assert_ne!(castling.zobrist_key(), no_castling.zobrist_key());
    }

    #[test]
    fn incremental_key_matches_reconstruction_for_special_moves() {
        for fen in [
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        ] {
            let root = Position::from_fen(fen).expect("test FEN");
            assert_eq!(root.zobrist_key(), root.recomputed_zobrist_key());
            for &mv in &root.legal_moves() {
                let mut child = root.clone();
                let undo = child.make_move(mv);
                assert_eq!(child.zobrist_key(), child.recomputed_zobrist_key());
                child.unmake_move(mv, undo);
                assert_eq!(child.zobrist_key(), child.recomputed_zobrist_key());
                assert_eq!(child, root);
            }
        }
    }
}
