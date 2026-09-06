use crate::{CastlingRights, ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square};

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
struct CapturedPiece {
    piece: Piece,
    square: Square,
}

/// Fixed-size state required to reverse one generated move exactly.
///
/// The moving piece and most geometry are recoverable from the move itself and the post-move
/// board, so the undo record stores only information destroyed by the forward transition.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Undo {
    captured: Option<CapturedPiece>,
    castling: CastlingRights,
    en_passant: Option<Square>,
    halfmove_clock: u16,
    fullmove_number: u16,
}

impl Position {
    /// Apply a move previously produced by [`Position::legal_moves`].
    ///
    /// This is the reversible engine transition. It intentionally does not regenerate moves or
    /// re-check king safety: callers in search already possess a legal move. Passing an arbitrary
    /// hand-constructed illegal move violates this method's contract and may panic.
    #[must_use]
    pub fn make_move(&mut self, mv: ChessMove) -> Undo {
        let us = self.side_to_move();
        let moving = self
            .piece_at(mv.from())
            .expect("generated move must have an origin piece");
        debug_assert_eq!(moving.color(), us);
        debug_assert!(self.reference_after(mv).is_some());

        let captured = captured_piece(self, us, mv);
        let castle = castle_rook_squares(us, mv.kind(), mv.from(), mv.to());
        if let Some((rook_from, _)) = castle {
            debug_assert_eq!(
                self.piece_at(rook_from),
                Some(Piece::new(us, PieceKind::Rook))
            );
        }

        let undo = Undo {
            captured,
            castling: self.castling_rights(),
            en_passant: self.en_passant(),
            halfmove_clock: self.halfmove_clock(),
            fullmove_number: self.fullmove_number(),
        };

        self.take_piece(mv.from())
            .expect("origin was checked before mutation");
        if let Some(captured) = captured {
            let removed = self
                .take_piece(captured.square)
                .expect("generated capture must have a captured piece");
            debug_assert_eq!(removed, captured.piece);
        }

        match mv.kind() {
            MoveKind::PromoteKnight
            | MoveKind::PromoteBishop
            | MoveKind::PromoteRook
            | MoveKind::PromoteQueen
            | MoveKind::PromoteCaptureKnight
            | MoveKind::PromoteCaptureBishop
            | MoveKind::PromoteCaptureRook
            | MoveKind::PromoteCaptureQueen => {
                let promoted = mv
                    .kind()
                    .promotion_piece()
                    .expect("promotion move has a promotion piece");
                self.place_piece(Piece::new(us, promoted), mv.to());
            }
            MoveKind::KingCastle | MoveKind::QueenCastle => {
                let (rook_from, rook_to) = castle.expect("castle geometry is fixed");
                let rook = self
                    .take_piece(rook_from)
                    .expect("generated castle must have its rook");
                self.place_piece(moving, mv.to());
                self.place_piece(rook, rook_to);
            }
            _ => self.place_piece(moving, mv.to()),
        }

        let mut rights = rights_after_moving_piece(undo.castling, moving, mv.from());
        if let Some(captured) = captured {
            rights = rights_after_captured_piece(rights, captured.piece, captured.square);
        }
        self.set_castling_rights(rights);

        self.set_en_passant(if mv.kind() == MoveKind::DoublePawnPush {
            let rank = (mv.from().rank() + mv.to().rank()) / 2;
            Square::from_file_rank(mv.from().file(), rank)
        } else {
            None
        });

        let halfmove = if moving.kind() == PieceKind::Pawn || mv.kind().is_capture() {
            0
        } else {
            undo.halfmove_clock.saturating_add(1)
        };
        let fullmove = if us == Color::Black {
            undo.fullmove_number.saturating_add(1)
        } else {
            undo.fullmove_number
        };
        self.set_clocks(halfmove, fullmove);
        self.set_side_to_move(us.opposite());

        debug_assert!(self.structural_invariants_hold());
        undo
    }

    /// Reverse exactly one preceding [`Position::make_move`] call.
    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {
        let us = self.side_to_move().opposite();

        match mv.kind() {
            MoveKind::PromoteKnight
            | MoveKind::PromoteBishop
            | MoveKind::PromoteRook
            | MoveKind::PromoteQueen
            | MoveKind::PromoteCaptureKnight
            | MoveKind::PromoteCaptureBishop
            | MoveKind::PromoteCaptureRook
            | MoveKind::PromoteCaptureQueen => {
                let promoted = self
                    .take_piece(mv.to())
                    .expect("made promotion must have a destination piece");
                debug_assert_eq!(promoted.color(), us);
                debug_assert_eq!(promoted.kind(), mv.kind().promotion_piece().expect("promotion"));
                self.place_piece(Piece::new(us, PieceKind::Pawn), mv.from());
            }
            MoveKind::KingCastle | MoveKind::QueenCastle => {
                let king = self
                    .take_piece(mv.to())
                    .expect("made castle must have a destination king");
                debug_assert_eq!(king, Piece::new(us, PieceKind::King));
                let (rook_from, rook_to) = castle_rook_squares(us, mv.kind(), mv.from(), mv.to())
                    .expect("castle geometry is fixed");
                let rook = self
                    .take_piece(rook_to)
                    .expect("made castle must have a moved rook");
                debug_assert_eq!(rook, Piece::new(us, PieceKind::Rook));
                self.place_piece(king, mv.from());
                self.place_piece(rook, rook_from);
            }
            _ => {
                let moving = self
                    .take_piece(mv.to())
                    .expect("made move must have a destination piece");
                debug_assert_eq!(moving.color(), us);
                self.place_piece(moving, mv.from());
            }
        }

        if let Some(captured) = undo.captured {
            self.place_piece(captured.piece, captured.square);
        }

        self.set_castling_rights(undo.castling);
        self.set_en_passant(undo.en_passant);
        self.set_clocks(undo.halfmove_clock, undo.fullmove_number);
        self.set_side_to_move(us);

        debug_assert!(self.structural_invariants_hold());
    }
}

fn captured_piece(position: &Position, us: Color, mv: ChessMove) -> Option<CapturedPiece> {
    let square = match mv.kind() {
        MoveKind::EnPassant => en_passant_capture_square(us, mv.to())?,
        kind if kind.is_capture() => mv.to(),
        _ => return None,
    };
    let piece = position
        .piece_at(square)
        .expect("generated capture must identify an occupied capture square");
    debug_assert_eq!(piece.color(), us.opposite());
    debug_assert_ne!(piece.kind(), PieceKind::King);
    Some(CapturedPiece { piece, square })
}

fn en_passant_capture_square(color: Color, destination: Square) -> Option<Square> {
    let rank = match color {
        Color::White => destination.rank().checked_sub(1)?,
        Color::Black => destination.rank().checked_add(1)?,
    };
    Square::from_file_rank(destination.file(), rank)
}

fn castle_rook_squares(
    color: Color,
    kind: MoveKind,
    king_from: Square,
    king_to: Square,
) -> Option<(Square, Square)> {
    let rank = match color {
        Color::White => 0,
        Color::Black => 7,
    };
    if king_from != Square::from_file_rank(4, rank)? {
        return None;
    }
    let (king_file, rook_from_file, rook_to_file) = match kind {
        MoveKind::KingCastle => (6, 7, 5),
        MoveKind::QueenCastle => (2, 0, 3),
        _ => return None,
    };
    if king_to != Square::from_file_rank(king_file, rank)? {
        return None;
    }
    Some((
        Square::from_file_rank(rook_from_file, rank)?,
        Square::from_file_rank(rook_to_file, rank)?,
    ))
}

fn rights_after_moving_piece(rights: CastlingRights, piece: Piece, from: Square) -> CastlingRights {
    match piece.kind() {
        PieceKind::King => match piece.color() {
            Color::White => {
                rights.without(CastlingRights::WHITE_KING.union(CastlingRights::WHITE_QUEEN))
            }
            Color::Black => {
                rights.without(CastlingRights::BLACK_KING.union(CastlingRights::BLACK_QUEEN))
            }
        },
        PieceKind::Rook => rights_after_rook_square(rights, piece.color(), from),
        _ => rights,
    }
}

fn rights_after_captured_piece(
    rights: CastlingRights,
    piece: Piece,
    square: Square,
) -> CastlingRights {
    if piece.kind() == PieceKind::Rook {
        rights_after_rook_square(rights, piece.color(), square)
    } else {
        rights
    }
}

fn rights_after_rook_square(
    rights: CastlingRights,
    color: Color,
    square: Square,
) -> CastlingRights {
    let rank = match color {
        Color::White => 0,
        Color::Black => 7,
    };
    if square == Square::from_file_rank(0, rank).expect("valid rook square") {
        rights.without(match color {
            Color::White => CastlingRights::WHITE_QUEEN,
            Color::Black => CastlingRights::BLACK_QUEEN,
        })
    } else if square == Square::from_file_rank(7, rank).expect("valid rook square") {
        rights.without(match color {
            Color::White => CastlingRights::WHITE_KING,
            Color::Black => CastlingRights::BLACK_KING,
        })
    } else {
        rights
    }
}

#[cfg(test)]
mod tests {
    use crate::{ChessMove, Position, Undo};

    fn assert_all_moves_match_reference(position: Position) {
        for &mv in &position.legal_moves() {
            let expected = position
                .reference_after(mv)
                .expect("legal move has reference result");
            let mut actual = position.clone();
            let undo = actual.make_move(mv);
            assert_eq!(actual, expected, "forward mismatch for {mv:?}");
            actual.unmake_move(mv, undo);
            assert_eq!(actual, position, "undo mismatch for {mv:?}");
        }
    }

    #[test]
    fn reversible_transition_matches_reference_across_special_positions() {
        for fen in [
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        ] {
            assert_all_moves_match_reference(Position::from_fen(fen).expect("test FEN"));
        }
    }

    #[test]
    fn deterministic_playout_round_trips_exactly() {
        let initial = Position::startpos();
        let mut position = initial.clone();
        let mut history: Vec<(ChessMove, Undo)> = Vec::new();
        let mut state = 0x9e37_79b9_7f4a_7c15_u64;

        for _ in 0..192 {
            let moves = position.legal_moves();
            if moves.is_empty() {
                break;
            }
            state ^= state << 13;
            state ^= state >> 7;
            state ^= state << 17;
            let mv = moves[state as usize % moves.len()];
            let expected = position
                .reference_after(mv)
                .expect("selected legal move has reference result");
            let undo = position.make_move(mv);
            assert_eq!(position, expected);
            history.push((mv, undo));
        }

        while let Some((mv, undo)) = history.pop() {
            position.unmake_move(mv, undo);
        }
        assert_eq!(position, initial);
    }
}
