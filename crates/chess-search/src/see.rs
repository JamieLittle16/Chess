use chess_core::{
    Bitboard, ChessMove, Color, MoveKind, Piece, PieceKind, Position, Square, bishop_attacks,
    king_attacks, knight_attacks, pawn_attacks, rook_attacks,
};

const SEE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 20_000];
const MAX_EXCHANGE_PLY: usize = 32;

/// Static exchange evaluation for a legal tactical move.
///
/// The calculation is deliberately independent of move generation and `Position` mutation. It
/// copies only the twelve piece bitboards into a small stack-local exchange state, then alternates
/// least-valuable legal attackers on the destination square. Removing each attacker from occupancy
/// naturally rediscovers bishop/rook/queen x-rays. Candidate recaptures that leave their own king in
/// check are excluded, so pinned pieces and illegal king captures do not distort the result.
///
/// Positive values favour the side making `mv`; negative values mean the exchange loses material.
pub(super) fn static_exchange_eval(position: &Position, mv: ChessMove) -> i32 {
    let Some(mover) = position.piece_at(mv.from()) else {
        return 0;
    };
    let us = mover.color();
    let target = mv.to();
    let captured = captured_piece(position, mv);

    let moved_kind = mv.kind().promotion_piece().unwrap_or(mover.kind());
    let promotion_gain = piece_value(moved_kind) - piece_value(mover.kind());
    let captured_gain = captured.map_or(0, |(piece, _)| piece_value(piece.kind()));

    if !mv.kind().is_capture() && !mv.kind().is_promotion() {
        return 0;
    }

    let mut state = SeeState::from_position(position);
    state.remove(us, mover.kind(), mv.from());
    if let Some((piece, square)) = captured {
        state.remove(piece.color(), piece.kind(), square);
    }
    state.add(us, moved_kind, target);

    let mut gains = [0_i32; MAX_EXCHANGE_PLY];
    gains[0] = captured_gain + promotion_gain;
    let mut depth = 0_usize;
    let mut side = us.opposite();
    let mut occupant_color = us;
    let mut occupant_kind = moved_kind;

    while depth + 1 < MAX_EXCHANGE_PLY {
        let Some(attacker) =
            state.least_valuable_legal_attacker(target, side, occupant_color, occupant_kind)
        else {
            break;
        };

        depth += 1;
        let resulting_kind = promoted_capture_kind(side, attacker.kind, target);
        let recapture_promotion_gain = piece_value(resulting_kind) - piece_value(attacker.kind);
        gains[depth] = piece_value(occupant_kind) + recapture_promotion_gain - gains[depth - 1];

        state.capture(
            side,
            attacker.kind,
            attacker.square,
            target,
            occupant_color,
            occupant_kind,
            resulting_kind,
        );
        occupant_color = side;
        occupant_kind = resulting_kind;
        side = side.opposite();
    }

    while depth > 0 {
        gains[depth - 1] = -(-gains[depth - 1]).max(gains[depth]);
        depth -= 1;
    }
    gains[0]
}

#[derive(Clone, Copy)]
struct Attacker {
    square: Square,
    kind: PieceKind,
}

#[derive(Clone, Copy)]
struct SeeState {
    pieces: [[Bitboard; 6]; 2],
    occupied: Bitboard,
}

impl SeeState {
    fn from_position(position: &Position) -> Self {
        let mut pieces = [[Bitboard::EMPTY; 6]; 2];
        for color in Color::ALL {
            for kind in PieceKind::ALL {
                pieces[color.index()][kind.index()] = position.pieces(color, kind);
            }
        }
        Self {
            pieces,
            occupied: position.occupied(),
        }
    }

    fn pieces(self, color: Color, kind: PieceKind) -> Bitboard {
        self.pieces[color.index()][kind.index()]
    }

    fn remove(&mut self, color: Color, kind: PieceKind, square: Square) {
        debug_assert!(self.pieces(color, kind).contains(square));
        self.pieces[color.index()][kind.index()] = self.pieces(color, kind).without(square);
        self.occupied = self.occupied.without(square);
    }

    fn add(&mut self, color: Color, kind: PieceKind, square: Square) {
        debug_assert!(!self.occupied.contains(square));
        self.pieces[color.index()][kind.index()] = self.pieces(color, kind).with(square);
        self.occupied = self.occupied.with(square);
    }

    #[allow(clippy::too_many_arguments)]
    fn capture(
        &mut self,
        side: Color,
        attacker_kind: PieceKind,
        from: Square,
        target: Square,
        victim_color: Color,
        victim_kind: PieceKind,
        resulting_kind: PieceKind,
    ) {
        self.remove(victim_color, victim_kind, target);
        self.remove(side, attacker_kind, from);
        self.add(side, resulting_kind, target);
    }

    fn attackers_to(self, target: Square, side: Color) -> Bitboard {
        let pawns = pawn_attacks(side.opposite(), target) & self.pieces(side, PieceKind::Pawn);
        let knights = knight_attacks(target) & self.pieces(side, PieceKind::Knight);
        let kings = king_attacks(target) & self.pieces(side, PieceKind::King);
        let diagonal = bishop_attacks(target, self.occupied)
            & (self.pieces(side, PieceKind::Bishop) | self.pieces(side, PieceKind::Queen));
        let orthogonal = rook_attacks(target, self.occupied)
            & (self.pieces(side, PieceKind::Rook) | self.pieces(side, PieceKind::Queen));
        pawns | knights | kings | diagonal | orthogonal
    }

    fn least_valuable_legal_attacker(
        self,
        target: Square,
        side: Color,
        victim_color: Color,
        victim_kind: PieceKind,
    ) -> Option<Attacker> {
        let attackers = self.attackers_to(target, side);
        for kind in PieceKind::ALL {
            let candidates = attackers & self.pieces(side, kind);
            for square in candidates {
                let resulting_kind = promoted_capture_kind(side, kind, target);
                let mut next = self;
                next.capture(
                    side,
                    kind,
                    square,
                    target,
                    victim_color,
                    victim_kind,
                    resulting_kind,
                );
                let Some(king) = next.king_square(side) else {
                    continue;
                };
                if !next.square_attacked(king, side.opposite()) {
                    return Some(Attacker { square, kind });
                }
            }
        }
        None
    }

    fn king_square(self, side: Color) -> Option<Square> {
        let mut kings = self.pieces(side, PieceKind::King);
        if kings.count() != 1 {
            return None;
        }
        kings.pop_lsb()
    }

    fn square_attacked(self, square: Square, attacker: Color) -> bool {
        if !(pawn_attacks(attacker.opposite(), square) & self.pieces(attacker, PieceKind::Pawn))
            .is_empty()
        {
            return true;
        }
        if !(knight_attacks(square) & self.pieces(attacker, PieceKind::Knight)).is_empty() {
            return true;
        }
        if !(king_attacks(square) & self.pieces(attacker, PieceKind::King)).is_empty() {
            return true;
        }
        if !(bishop_attacks(square, self.occupied)
            & (self.pieces(attacker, PieceKind::Bishop) | self.pieces(attacker, PieceKind::Queen)))
        .is_empty()
        {
            return true;
        }
        !(rook_attacks(square, self.occupied)
            & (self.pieces(attacker, PieceKind::Rook) | self.pieces(attacker, PieceKind::Queen)))
        .is_empty()
    }
}

fn captured_piece(position: &Position, mv: ChessMove) -> Option<(Piece, Square)> {
    if mv.kind() == MoveKind::EnPassant {
        let square = Square::from_file_rank(mv.to().file(), mv.from().rank())?;
        position.piece_at(square).map(|piece| (piece, square))
    } else {
        position.piece_at(mv.to()).map(|piece| (piece, mv.to()))
    }
}

fn promoted_capture_kind(side: Color, kind: PieceKind, target: Square) -> PieceKind {
    if kind != PieceKind::Pawn {
        return kind;
    }
    let promotion_rank = match side {
        Color::White => 7,
        Color::Black => 0,
    };
    if target.rank() == promotion_rank {
        PieceKind::Queen
    } else {
        PieceKind::Pawn
    }
}

fn piece_value(kind: PieceKind) -> i32 {
    SEE_VALUES[kind.index()]
}

#[cfg(test)]
mod tests {
    use chess_core::{MoveKind, Position, Square};

    use super::static_exchange_eval;

    fn find_move(
        position: &Position,
        from: (u8, u8),
        to: (u8, u8),
        kind: Option<MoveKind>,
    ) -> chess_core::ChessMove {
        let from = Square::from_file_rank(from.0, from.1).expect("from square");
        let to = Square::from_file_rank(to.0, to.1).expect("to square");
        position
            .legal_moves()
            .as_slice()
            .iter()
            .copied()
            .find(|mv| {
                mv.from() == from && mv.to() == to && kind.is_none_or(|kind| mv.kind() == kind)
            })
            .expect("requested move is legal")
    }

    #[test]
    fn undefended_capture_wins_the_victim() {
        let position = Position::from_fen("7k/3q4/8/8/8/8/3R4/K7 w - - 0 1").expect("valid FEN");
        let capture = find_move(&position, (3, 1), (3, 6), None);
        assert_eq!(static_exchange_eval(&position, capture), 900);
    }

    #[test]
    fn poisoned_capture_accounts_for_the_recapture() {
        let position = Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
        let capture = find_move(&position, (3, 0), (3, 6), None);
        assert_eq!(static_exchange_eval(&position, capture), -800);
    }

    #[test]
    fn pinned_recapturer_is_not_counted_as_legal() {
        let position =
            Position::from_fen("4k3/3pr3/8/8/6B1/8/8/3QR1K1 w - - 0 1").expect("valid FEN");
        let capture = find_move(&position, (3, 0), (3, 6), None);
        assert_eq!(static_exchange_eval(&position, capture), 100);
    }

    #[test]
    fn quiet_promotion_includes_the_material_upgrade() {
        let position = Position::from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        let promotion = find_move(&position, (0, 6), (0, 7), Some(MoveKind::PromoteQueen));
        assert_eq!(static_exchange_eval(&position, promotion), 800);
    }
}
