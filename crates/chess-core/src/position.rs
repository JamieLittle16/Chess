use crate::{Bitboard, Color, FenError, Piece, PieceKind, Square, ZobristKey};

const PIECE_SLOTS: usize = 12;

/// Castling permissions stored as four independent bits.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
#[repr(transparent)]
pub struct CastlingRights(u8);

impl CastlingRights {
    pub const NONE: Self = Self(0);
    pub const WHITE_KING: Self = Self(1 << 0);
    pub const WHITE_QUEEN: Self = Self(1 << 1);
    pub const BLACK_KING: Self = Self(1 << 2);
    pub const BLACK_QUEEN: Self = Self(1 << 3);
    pub const ALL: Self = Self(0b1111);

    #[must_use]
    pub const fn contains(self, rights: Self) -> bool {
        self.0 & rights.0 == rights.0
    }

    #[must_use]
    pub const fn union(self, rights: Self) -> Self {
        Self(self.0 | rights.0)
    }

    #[must_use]
    pub const fn without(self, rights: Self) -> Self {
        Self(self.0 & !rights.0)
    }
}

/// Complete persistent chess position state.
///
/// Search-only caches, evaluation accumulators and undo stacks deliberately live elsewhere.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Position {
    pieces: [Bitboard; PIECE_SLOTS],
    occupancy: [Bitboard; 2],
    occupied: Bitboard,
    side_to_move: Color,
    castling: CastlingRights,
    en_passant: Option<Square>,
    halfmove_clock: u16,
    fullmove_number: u16,
    zobrist: ZobristKey,
}

impl Position {
    #[must_use]
    pub const fn empty() -> Self {
        Self {
            pieces: [Bitboard::EMPTY; PIECE_SLOTS],
            occupancy: [Bitboard::EMPTY; 2],
            occupied: Bitboard::EMPTY,
            side_to_move: Color::White,
            castling: CastlingRights::NONE,
            en_passant: None,
            halfmove_clock: 0,
            fullmove_number: 1,
            zobrist: ZobristKey::ZERO,
        }
    }

    /// Parse a complete six-field FEN string.
    pub fn from_fen(fen: &str) -> Result<Self, FenError> {
        crate::fen::parse(fen)
    }

    /// Standard chess initial position.
    #[must_use]
    pub fn startpos() -> Self {
        Self::from_fen(crate::fen::STARTPOS_FEN).expect("the built-in start FEN is valid")
    }

    #[must_use]
    pub const fn side_to_move(&self) -> Color {
        self.side_to_move
    }

    #[must_use]
    pub const fn castling_rights(&self) -> CastlingRights {
        self.castling
    }

    #[must_use]
    pub const fn en_passant(&self) -> Option<Square> {
        self.en_passant
    }

    #[must_use]
    pub const fn halfmove_clock(&self) -> u16 {
        self.halfmove_clock
    }

    #[must_use]
    pub const fn fullmove_number(&self) -> u16 {
        self.fullmove_number
    }

    #[must_use]
    pub const fn zobrist_key(&self) -> ZobristKey {
        self.zobrist
    }

    /// Reconstruct the search identity from canonical chess state.
    ///
    /// This is an oracle for tests and diagnostics; search should use [`Position::zobrist_key`].
    #[must_use]
    pub fn recomputed_zobrist_key(&self) -> ZobristKey {
        crate::zobrist::recompute(self)
    }

    #[must_use]
    pub const fn occupied(&self) -> Bitboard {
        self.occupied
    }

    #[must_use]
    pub const fn occupancy(&self, color: Color) -> Bitboard {
        self.occupancy[color.index()]
    }

    #[must_use]
    pub const fn pieces(&self, color: Color, kind: PieceKind) -> Bitboard {
        self.pieces[Piece::new(color, kind).slot()]
    }

    #[must_use]
    pub fn king_square(&self, color: Color) -> Option<Square> {
        let mut kings = self.pieces(color, PieceKind::King);
        if kings.count() != 1 {
            return None;
        }
        kings.pop_lsb()
    }

    #[must_use]
    pub fn piece_at(&self, square: Square) -> Option<Piece> {
        if !self.occupied.contains(square) {
            return None;
        }
        for slot in 0..PIECE_SLOTS {
            if self.pieces[slot].contains(square) {
                return Piece::from_slot(slot);
            }
        }
        debug_assert!(false, "occupied cache disagrees with piece bitboards");
        None
    }

    pub(crate) fn put_piece(&mut self, piece: Piece, square: Square) -> Result<(), FenError> {
        if self.occupied.contains(square) {
            return Err(FenError::OverlappingPieces);
        }
        self.place_piece(piece, square);
        Ok(())
    }

    pub(crate) fn place_piece(&mut self, piece: Piece, square: Square) {
        debug_assert!(!self.occupied.contains(square));
        self.pieces[piece.slot()] = self.pieces[piece.slot()].with(square);
        self.occupancy[piece.color().index()] = self.occupancy[piece.color().index()].with(square);
        self.occupied = self.occupied.with(square);
        self.zobrist
            .toggle(crate::zobrist::piece_component(piece, square));
    }

    pub(crate) fn take_piece(&mut self, square: Square) -> Option<Piece> {
        let piece = self.piece_at(square)?;
        self.pieces[piece.slot()] = self.pieces[piece.slot()].without(square);
        self.occupancy[piece.color().index()] =
            self.occupancy[piece.color().index()].without(square);
        self.occupied = self.occupied.without(square);
        self.zobrist
            .toggle(crate::zobrist::piece_component(piece, square));
        Some(piece)
    }

    pub(crate) fn set_side_to_move(&mut self, color: Color) {
        self.zobrist
            .toggle(crate::zobrist::side_component(self.side_to_move));
        self.side_to_move = color;
        self.zobrist
            .toggle(crate::zobrist::side_component(self.side_to_move));
    }

    pub(crate) fn set_castling_rights(&mut self, rights: CastlingRights) {
        self.zobrist
            .toggle(crate::zobrist::castling_component(self.castling));
        self.castling = rights;
        self.zobrist
            .toggle(crate::zobrist::castling_component(self.castling));
    }

    pub(crate) fn set_en_passant(&mut self, square: Option<Square>) {
        self.zobrist
            .toggle(crate::zobrist::en_passant_component(self.en_passant));
        self.en_passant = square;
        self.zobrist
            .toggle(crate::zobrist::en_passant_component(self.en_passant));
    }

    pub(crate) fn set_clocks(&mut self, halfmove: u16, fullmove: u16) {
        self.halfmove_clock = halfmove;
        self.fullmove_number = fullmove;
    }

    #[must_use]
    pub fn structural_invariants_hold(&self) -> bool {
        let mut union = Bitboard::EMPTY;
        for board in self.pieces {
            if !(union & board).is_empty() {
                return false;
            }
            union = union | board;
        }

        let mut white = Bitboard::EMPTY;
        for kind in PieceKind::ALL {
            white = white | self.pieces(Color::White, kind);
        }
        let mut black = Bitboard::EMPTY;
        for kind in PieceKind::ALL {
            black = black | self.pieces(Color::Black, kind);
        }

        union == self.occupied
            && white == self.occupancy(Color::White)
            && black == self.occupancy(Color::Black)
            && (white & black).is_empty()
            && self.zobrist == crate::zobrist::recompute(self)
    }
}

impl Default for Position {
    fn default() -> Self {
        Self::empty()
    }
}
