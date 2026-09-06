use crate::{
    CastlingRights, ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square,
};

impl Position {
    /// Apply one move by cloning the position and performing a simple semantic transition.
    ///
    /// This path is intentionally not the future search hot path. It is kept simple so M2's
    /// reversible make/unmake implementation can be differential-tested against an independent
    /// oracle.
    #[must_use]
    pub fn reference_after(&self, mv: ChessMove) -> Option<Self> {
        let moving = self.piece_at(mv.from())?;
        let us = self.side_to_move();
        if moving.color() != us {
            return None;
        }

        let target = self.piece_at(mv.to());
        if target.is_some_and(|piece| piece.color() == us || piece.kind() == PieceKind::King) {
            return None;
        }

        let kind = mv.kind();
        validate_move_shape(self, moving, mv, target)?;

        let mut next = self.clone();
        let mut captured = None;
        let mut capture_square = None;

        next.take_piece(mv.from())?;

        match kind {
            MoveKind::Quiet | MoveKind::DoublePawnPush => {
                next.place_piece(moving, mv.to());
            }
            MoveKind::Capture => {
                captured = next.take_piece(mv.to());
                capture_square = Some(mv.to());
                next.place_piece(moving, mv.to());
            }
            MoveKind::EnPassant => {
                let square = en_passant_capture_square(us, mv.to())?;
                captured = next.take_piece(square);
                capture_square = Some(square);
                next.place_piece(moving, mv.to());
            }
            MoveKind::PromoteKnight
            | MoveKind::PromoteBishop
            | MoveKind::PromoteRook
            | MoveKind::PromoteQueen => {
                next.place_piece(Piece::new(us, kind.promotion_piece()?), mv.to());
            }
            MoveKind::PromoteCaptureKnight
            | MoveKind::PromoteCaptureBishop
            | MoveKind::PromoteCaptureRook
            | MoveKind::PromoteCaptureQueen => {
                captured = next.take_piece(mv.to());
                capture_square = Some(mv.to());
                next.place_piece(Piece::new(us, kind.promotion_piece()?), mv.to());
            }
            MoveKind::KingCastle | MoveKind::QueenCastle => {
                let (rook_from, rook_to) = castle_rook_squares(us, kind, mv.from(), mv.to())?;
                let rook = next.take_piece(rook_from)?;
                if rook != Piece::new(us, PieceKind::Rook) {
                    return None;
                }
                next.place_piece(moving, mv.to());
                next.place_piece(rook, rook_to);
            }
        }

        if kind.is_capture() && captured.is_none() {
            return None;
        }

        let mut rights = rights_after_moving_piece(self.castling_rights(), moving, mv.from());
        if let (Some(piece), Some(square)) = (captured, capture_square) {
            rights = rights_after_captured_piece(rights, piece, square);
        }
        next.set_castling_rights(rights);

        let new_en_passant = if kind == MoveKind::DoublePawnPush {
            let rank = (mv.from().rank() + mv.to().rank()) / 2;
            Square::from_file_rank(mv.from().file(), rank)
        } else {
            None
        };
        next.set_en_passant(new_en_passant);

        let halfmove = if moving.kind() == PieceKind::Pawn || kind.is_capture() {
            0
        } else {
            self.halfmove_clock().saturating_add(1)
        };
        let fullmove = if us == Color::Black {
            self.fullmove_number().saturating_add(1)
        } else {
            self.fullmove_number()
        };
        next.set_clocks(halfmove, fullmove);
        next.set_side_to_move(us.opposite());

        debug_assert!(next.structural_invariants_hold());
        Some(next)
    }
}

fn validate_move_shape(
    position: &Position,
    moving: Piece,
    mv: ChessMove,
    target: Option<Piece>,
) -> Option<()> {
    let us = moving.color();
    let kind = mv.kind();

    match kind {
        MoveKind::Quiet => {
            if target.is_some() {
                return None;
            }
        }
        MoveKind::DoublePawnPush => {
            if moving.kind() != PieceKind::Pawn || target.is_some() {
                return None;
            }
            let start_rank = match us {
                Color::White => 1,
                Color::Black => 6,
            };
            let expected_delta = match us {
                Color::White => 2_i8,
                Color::Black => -2_i8,
            };
            if mv.from().rank() != start_rank
                || mv.from().file() != mv.to().file()
                || mv.to().rank() as i8 - mv.from().rank() as i8 != expected_delta
            {
                return None;
            }
        }
        MoveKind::Capture => {
            if target.is_none() {
                return None;
            }
        }
        MoveKind::EnPassant => {
            if moving.kind() != PieceKind::Pawn
                || target.is_some()
                || position.en_passant() != Some(mv.to())
            {
                return None;
            }
            let captured = en_passant_capture_square(us, mv.to())?;
            if position.piece_at(captured) != Some(Piece::new(us.opposite(), PieceKind::Pawn)) {
                return None;
            }
        }
        MoveKind::PromoteKnight
        | MoveKind::PromoteBishop
        | MoveKind::PromoteRook
        | MoveKind::PromoteQueen => {
            if moving.kind() != PieceKind::Pawn
                || target.is_some()
                || !is_promotion_rank(us, mv.to())
            {
                return None;
            }
        }
        MoveKind::PromoteCaptureKnight
        | MoveKind::PromoteCaptureBishop
        | MoveKind::PromoteCaptureRook
        | MoveKind::PromoteCaptureQueen => {
            if moving.kind() != PieceKind::Pawn
                || target.is_none()
                || !is_promotion_rank(us, mv.to())
            {
                return None;
            }
        }
        MoveKind::KingCastle | MoveKind::QueenCastle => {
            if moving.kind() != PieceKind::King || target.is_some() {
                return None;
            }
            let required = match (us, kind) {
                (Color::White, MoveKind::KingCastle) => CastlingRights::WHITE_KING,
                (Color::White, MoveKind::QueenCastle) => CastlingRights::WHITE_QUEEN,
                (Color::Black, MoveKind::KingCastle) => CastlingRights::BLACK_KING,
                (Color::Black, MoveKind::QueenCastle) => CastlingRights::BLACK_QUEEN,
                _ => return None,
            };
            if !position.castling_rights().contains(required) {
                return None;
            }
            let (rook_from, _) = castle_rook_squares(us, kind, mv.from(), mv.to())?;
            if position.piece_at(rook_from) != Some(Piece::new(us, PieceKind::Rook)) {
                return None;
            }
        }
    }

    Some(())
}

fn is_promotion_rank(color: Color, square: Square) -> bool {
    square.rank()
        == match color {
            Color::White => 7,
            Color::Black => 0,
        }
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
    let expected_king_from = Square::from_file_rank(4, rank)?;
    if king_from != expected_king_from {
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

fn rights_after_moving_piece(
    rights: CastlingRights,
    piece: Piece,
    from: Square,
) -> CastlingRights {
    match piece.kind() {
        PieceKind::King => match piece.color() {
            Color::White => rights.without(CastlingRights::WHITE_KING.union(CastlingRights::WHITE_QUEEN)),
            Color::Black => rights.without(CastlingRights::BLACK_KING.union(CastlingRights::BLACK_QUEEN)),
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
    use crate::{ChessMove, Color, MoveKind, PieceKind, Position, Square};

    #[test]
    fn reference_transition_updates_double_push_state() {
        let position = Position::startpos();
        let e2 = Square::from_file_rank(4, 1).expect("e2");
        let e4 = Square::from_file_rank(4, 3).expect("e4");
        let e3 = Square::from_file_rank(4, 2).expect("e3");
        let next = position
            .reference_after(ChessMove::new(e2, e4, MoveKind::DoublePawnPush))
            .expect("valid double push");

        assert_eq!(next.side_to_move(), Color::Black);
        assert_eq!(next.en_passant(), Some(e3));
        assert_eq!(next.halfmove_clock(), 0);
        assert_eq!(next.fullmove_number(), 1);
        assert!(next.pieces(Color::White, PieceKind::Pawn).contains(e4));
        assert!(!next.pieces(Color::White, PieceKind::Pawn).contains(e2));
        assert!(next.structural_invariants_hold());
    }
}
