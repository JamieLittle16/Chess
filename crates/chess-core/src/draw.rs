use crate::{ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square, ZobristKey};

impl Position {
    /// Position identity used for repetition adjudication.
    ///
    /// The transposition-table key deliberately preserves the exact FEN en-passant target. Chess
    /// repetition is slightly different: an en-passant target changes the position only when the
    /// side to move actually has a legal en-passant capture. Keeping the two identities separate
    /// avoids making the TT less conservative while preserving rule-correct repetition semantics.
    #[must_use]
    pub fn repetition_key(&self) -> ZobristKey {
        let mut key = self.zobrist_key();
        if let Some(target) = self.en_passant()
            && !has_legal_en_passant(self, target)
        {
            key.toggle(crate::zobrist::en_passant_component(Some(target)));
        }
        key
    }

    /// True for material configurations in which checkmate is impossible by any legal sequence.
    ///
    /// This deliberately recognizes only exact dead-material classes: bare kings; one bishop or
    /// knight against a bare king; and bishop-only positions where every bishop lives on the same
    /// square colour. Positions such as two knights versus king are *not* dead positions because a
    /// mating position can exist with cooperative play, even though mate cannot be forced.
    #[must_use]
    pub fn is_insufficient_material(&self) -> bool {
        for color in Color::ALL {
            if !self.pieces(color, PieceKind::Pawn).is_empty()
                || !self.pieces(color, PieceKind::Rook).is_empty()
                || !self.pieces(color, PieceKind::Queen).is_empty()
            {
                return false;
            }
        }

        let knights = self.pieces(Color::White, PieceKind::Knight).count()
            + self.pieces(Color::Black, PieceKind::Knight).count();
        let bishops = self.pieces(Color::White, PieceKind::Bishop).count()
            + self.pieces(Color::Black, PieceKind::Bishop).count();
        let minors = knights + bishops;

        if minors <= 1 {
            return true;
        }
        if knights != 0 {
            return false;
        }

        let mut square_colour = None;
        for color in Color::ALL {
            for square in self.pieces(color, PieceKind::Bishop) {
                let colour = (square.file() + square.rank()) & 1;
                if square_colour.is_some_and(|existing| existing != colour) {
                    return false;
                }
                square_colour = Some(colour);
            }
        }
        true
    }
}

fn has_legal_en_passant(position: &Position, target: Square) -> bool {
    let us = position.side_to_move();
    let origin_rank = match us {
        Color::White => target.rank().checked_sub(1),
        Color::Black => target.rank().checked_add(1),
    };
    let Some(origin_rank) = origin_rank else {
        return false;
    };

    for file in [target.file().checked_sub(1), target.file().checked_add(1)] {
        let Some(file) = file.filter(|file| *file < 8) else {
            continue;
        };
        let Some(from) = Square::from_file_rank(file, origin_rank) else {
            continue;
        };
        if position.piece_at(from) != Some(Piece::new(us, PieceKind::Pawn)) {
            continue;
        }

        let mv = ChessMove::new(from, target, MoveKind::EnPassant);
        if let Some(next) = position.reference_after(mv)
            && !next.is_in_check(us)
        {
            return true;
        }
    }
    false
}

#[cfg(test)]
mod tests {
    use crate::Position;

    #[test]
    fn irrelevant_en_passant_target_is_ignored_for_repetition() {
        let with_target = Position::from_fen("8/8/8/8/8/8/8/K6k w - e6 0 1").expect("valid FEN");
        let without_target = Position::from_fen("8/8/8/8/8/8/8/K6k w - - 0 1").expect("valid FEN");
        assert_ne!(with_target.zobrist_key(), without_target.zobrist_key());
        assert_eq!(
            with_target.repetition_key(),
            without_target.repetition_key()
        );
    }

    #[test]
    fn legal_en_passant_target_changes_repetition_identity() {
        let with_target = Position::from_fen("8/8/8/3pP3/8/8/8/K6k w - d6 0 1").expect("valid FEN");
        let without_target =
            Position::from_fen("8/8/8/3pP3/8/8/8/K6k w - - 0 1").expect("valid FEN");
        assert_ne!(
            with_target.repetition_key(),
            without_target.repetition_key()
        );
    }

    #[test]
    fn pinned_en_passant_target_is_ignored_for_repetition() {
        let with_target =
            Position::from_fen("4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1").expect("valid FEN");
        let without_target =
            Position::from_fen("4r2k/8/8/3pP3/8/8/8/4K3 w - - 0 1").expect("valid FEN");
        assert_eq!(
            with_target.repetition_key(),
            without_target.repetition_key()
        );
    }

    #[test]
    fn dead_material_classes_are_conservative() {
        for fen in [
            "7k/8/8/8/8/8/8/K7 w - - 0 1",
            "7k/8/8/8/8/8/6B1/K7 w - - 0 1",
            "7k/8/8/8/8/8/6N1/K7 w - - 0 1",
            "5b1k/8/8/8/8/8/6B1/K7 w - - 0 1",
        ] {
            assert!(
                Position::from_fen(fen)
                    .expect("valid FEN")
                    .is_insufficient_material()
            );
        }

        for fen in [
            "2b4k/8/8/8/8/8/6B1/K7 w - - 0 1",
            "7k/8/8/8/8/8/5NN1/K7 w - - 0 1",
            "7k/8/8/8/8/8/6P1/K7 w - - 0 1",
        ] {
            assert!(
                !Position::from_fen(fen)
                    .expect("valid FEN")
                    .is_insufficient_material()
            );
        }
    }
}
