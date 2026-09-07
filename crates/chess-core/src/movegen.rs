use crate::{
    Bitboard, CastlingRights, ChessMove, Color, MoveKind, MoveList, Piece, PieceKind, Position,
    Square, bishop_attacks, is_square_attacked, king_attacks, knight_attacks, pawn_attacks,
    queen_attacks, rook_attacks,
};

const QUIET_PROMOTIONS: [MoveKind; 4] = [
    MoveKind::PromoteQueen,
    MoveKind::PromoteRook,
    MoveKind::PromoteBishop,
    MoveKind::PromoteKnight,
];
const CAPTURE_PROMOTIONS: [MoveKind; 4] = [
    MoveKind::PromoteCaptureQueen,
    MoveKind::PromoteCaptureRook,
    MoveKind::PromoteCaptureBishop,
    MoveKind::PromoteCaptureKnight,
];

impl Position {
    /// Generate every legal move for the side to move without heap allocation.
    #[must_use]
    pub fn legal_moves(&self) -> MoveList {
        generate_legal_moves(self)
    }

    #[must_use]
    pub fn is_in_check(&self, color: Color) -> bool {
        self.king_square(color)
            .is_some_and(|king| is_square_attacked(self, king, color.opposite()))
    }
}

/// Generate every legal move while leaving `position` unchanged.
///
/// This convenience entry point clones the position once and delegates to the reversible hot-path
/// implementation. Search code that already owns a mutable working position should call
/// [`generate_legal_moves_mut`] directly and avoid even that single clone.
#[must_use]
pub fn generate_legal_moves(position: &Position) -> MoveList {
    let mut scratch = position.clone();
    generate_legal_moves_mut(&mut scratch)
}

/// Generate every legal move using reversible make/unmake on the supplied working position.
///
/// The position is exactly restored before this function returns.
#[must_use]
pub fn generate_legal_moves_mut(position: &mut Position) -> MoveList {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return MoveList::new();
    }

    let pseudo = generate_pseudo_legal_moves(position);
    filter_legal_moves(position, &pseudo, us)
}

/// Return whether the side to move has at least one legal move, restoring `position` exactly.
///
/// This deliberately shares the ordinary pseudo-legal generator and make/unmake legality test, but
/// stops at the first legal move. Search uses it only on nodes that may be discarded by a static
/// pruning decision, where constructing and legality-filtering every move would otherwise be wasted.
#[must_use]
pub fn has_legal_move_mut(position: &mut Position) -> bool {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return false;
    }

    let pseudo = generate_pseudo_legal_moves(position);
    for &mv in &pseudo {
        let undo = position.make_move(mv);
        let is_legal = position
            .king_square(us)
            .is_some_and(|king| !is_square_attacked(position, king, us.opposite()));
        position.unmake_move(mv, undo);
        if is_legal {
            return true;
        }
    }
    false
}

/// Generate only legal captures, en-passant moves and promotions.
///
/// This is the qsearch-facing hot path. It deliberately avoids constructing ordinary quiet pawn
/// pushes, quiet piece moves and castles, and therefore avoids making/unmaking those moves solely to
/// reject them after legality filtering. Quiet promotions remain tactical and are included.
///
/// Callers that need every legal check evasion must use [`generate_legal_moves_mut`]; this function
/// intentionally returns only the tactical subset even if the side to move is in check.
#[must_use]
pub fn generate_legal_tactical_moves_mut(position: &mut Position) -> MoveList {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return MoveList::new();
    }

    let pseudo = generate_pseudo_legal_tactical_moves(position);
    filter_legal_moves(position, &pseudo, us)
}

fn filter_legal_moves(position: &mut Position, pseudo: &MoveList, us: Color) -> MoveList {
    let mut legal = MoveList::new();
    for &mv in pseudo {
        let undo = position.make_move(mv);
        let is_legal = position
            .king_square(us)
            .is_some_and(|king| !is_square_attacked(position, king, us.opposite()));
        position.unmake_move(mv, undo);
        if is_legal {
            legal.push(mv);
        }
    }
    legal
}

fn generate_pseudo_legal_moves(position: &Position) -> MoveList {
    let mut moves = MoveList::new();
    let us = position.side_to_move();

    append_pawn_moves(position, us, &mut moves);
    append_piece_moves(position, us, PieceKind::Knight, &mut moves);
    append_piece_moves(position, us, PieceKind::Bishop, &mut moves);
    append_piece_moves(position, us, PieceKind::Rook, &mut moves);
    append_piece_moves(position, us, PieceKind::Queen, &mut moves);
    append_piece_moves(position, us, PieceKind::King, &mut moves);
    append_castles(position, us, &mut moves);

    moves
}

fn generate_pseudo_legal_tactical_moves(position: &Position) -> MoveList {
    let mut moves = MoveList::new();
    let us = position.side_to_move();

    append_pawn_tactical_moves(position, us, &mut moves);
    append_piece_captures(position, us, PieceKind::Knight, &mut moves);
    append_piece_captures(position, us, PieceKind::Bishop, &mut moves);
    append_piece_captures(position, us, PieceKind::Rook, &mut moves);
    append_piece_captures(position, us, PieceKind::Queen, &mut moves);
    append_piece_captures(position, us, PieceKind::King, &mut moves);

    moves
}

fn append_pawn_moves(position: &Position, us: Color, moves: &mut MoveList) {
    let them = us.opposite();
    let occupied = position.occupied();
    let enemy_king = position.pieces(them, PieceKind::King);
    let capturable = position.occupancy(them) & !enemy_king;
    let start_rank = match us {
        Color::White => 1,
        Color::Black => 6,
    };
    let promotion_rank = match us {
        Color::White => 7,
        Color::Black => 0,
    };

    for from in position.pieces(us, PieceKind::Pawn) {
        if let Some(one) = pawn_forward(from, us, 1)
            && !occupied.contains(one)
        {
            if one.rank() == promotion_rank {
                append_promotions(moves, from, one, false);
            } else {
                moves.push(ChessMove::new(from, one, MoveKind::Quiet));
                if from.rank() == start_rank
                    && let Some(two) = pawn_forward(from, us, 2)
                    && !occupied.contains(two)
                {
                    moves.push(ChessMove::new(from, two, MoveKind::DoublePawnPush));
                }
            }
        }

        append_pawn_captures(position, us, from, promotion_rank, capturable, moves);
    }
}

fn append_pawn_tactical_moves(position: &Position, us: Color, moves: &mut MoveList) {
    let them = us.opposite();
    let occupied = position.occupied();
    let enemy_king = position.pieces(them, PieceKind::King);
    let capturable = position.occupancy(them) & !enemy_king;
    let promotion_rank = match us {
        Color::White => 7,
        Color::Black => 0,
    };

    for from in position.pieces(us, PieceKind::Pawn) {
        // A non-capturing promotion changes material immediately and therefore belongs in qsearch.
        if let Some(one) = pawn_forward(from, us, 1)
            && one.rank() == promotion_rank
            && !occupied.contains(one)
        {
            append_promotions(moves, from, one, false);
        }

        append_pawn_captures(position, us, from, promotion_rank, capturable, moves);
    }
}

fn append_pawn_captures(
    position: &Position,
    us: Color,
    from: Square,
    promotion_rank: u8,
    capturable: Bitboard,
    moves: &mut MoveList,
) {
    let occupied = position.occupied();
    for to in pawn_attacks(us, from) {
        if capturable.contains(to) {
            if to.rank() == promotion_rank {
                append_promotions(moves, from, to, true);
            } else {
                moves.push(ChessMove::new(from, to, MoveKind::Capture));
            }
            continue;
        }

        if position.en_passant() == Some(to)
            && !occupied.contains(to)
            && en_passant_has_capturable_pawn(position, us, to)
        {
            moves.push(ChessMove::new(from, to, MoveKind::EnPassant));
        }
    }
}

fn append_promotions(moves: &mut MoveList, from: Square, to: Square, capture: bool) {
    let kinds = if capture {
        &CAPTURE_PROMOTIONS
    } else {
        &QUIET_PROMOTIONS
    };
    for &kind in kinds {
        moves.push(ChessMove::new(from, to, kind));
    }
}

fn append_piece_moves(position: &Position, us: Color, kind: PieceKind, moves: &mut MoveList) {
    let them = us.opposite();
    let occupied = position.occupied();
    let friendly = position.occupancy(us);
    let enemy = position.occupancy(them);
    let enemy_king = position.pieces(them, PieceKind::King);

    for from in position.pieces(us, kind) {
        let attacks = attacks_for_piece(kind, from, occupied);
        let targets = attacks & !friendly & !enemy_king;
        append_targets(moves, from, targets, enemy);
    }
}

fn append_piece_captures(position: &Position, us: Color, kind: PieceKind, moves: &mut MoveList) {
    let them = us.opposite();
    let occupied = position.occupied();
    let enemy_king = position.pieces(them, PieceKind::King);
    let capturable = position.occupancy(them) & !enemy_king;

    for from in position.pieces(us, kind) {
        let targets = attacks_for_piece(kind, from, occupied) & capturable;
        for to in targets {
            moves.push(ChessMove::new(from, to, MoveKind::Capture));
        }
    }
}

fn attacks_for_piece(kind: PieceKind, from: Square, occupied: Bitboard) -> Bitboard {
    match kind {
        PieceKind::Knight => knight_attacks(from),
        PieceKind::Bishop => bishop_attacks(from, occupied),
        PieceKind::Rook => rook_attacks(from, occupied),
        PieceKind::Queen => queen_attacks(from, occupied),
        PieceKind::King => king_attacks(from),
        PieceKind::Pawn => unreachable!("pawns are generated separately"),
    }
}

fn append_targets(moves: &mut MoveList, from: Square, targets: Bitboard, enemy: Bitboard) {
    for to in targets {
        let kind = if enemy.contains(to) {
            MoveKind::Capture
        } else {
            MoveKind::Quiet
        };
        moves.push(ChessMove::new(from, to, kind));
    }
}

fn append_castles(position: &Position, us: Color, moves: &mut MoveList) {
    let them = us.opposite();
    let rank = match us {
        Color::White => 0,
        Color::Black => 7,
    };
    let king_from = square(4, rank);
    if position.piece_at(king_from) != Some(Piece::new(us, PieceKind::King))
        || is_square_attacked(position, king_from, them)
    {
        return;
    }

    let king_right = match us {
        Color::White => CastlingRights::WHITE_KING,
        Color::Black => CastlingRights::BLACK_KING,
    };
    let queen_right = match us {
        Color::White => CastlingRights::WHITE_QUEEN,
        Color::Black => CastlingRights::BLACK_QUEEN,
    };

    if position.castling_rights().contains(king_right) {
        let rook = square(7, rank);
        let transit = square(5, rank);
        let destination = square(6, rank);
        if position.piece_at(rook) == Some(Piece::new(us, PieceKind::Rook))
            && !position.occupied().contains(transit)
            && !position.occupied().contains(destination)
            && king_step_is_safe(position, king_from, transit, them)
        {
            moves.push(ChessMove::new(king_from, destination, MoveKind::KingCastle));
        }
    }

    if position.castling_rights().contains(queen_right) {
        let rook = square(0, rank);
        let b_file = square(1, rank);
        let destination = square(2, rank);
        let transit = square(3, rank);
        if position.piece_at(rook) == Some(Piece::new(us, PieceKind::Rook))
            && !position.occupied().contains(b_file)
            && !position.occupied().contains(destination)
            && !position.occupied().contains(transit)
            && king_step_is_safe(position, king_from, transit, them)
        {
            moves.push(ChessMove::new(
                king_from,
                destination,
                MoveKind::QueenCastle,
            ));
        }
    }
}

fn king_step_is_safe(position: &Position, from: Square, to: Square, attacker: Color) -> bool {
    let Some(intermediate) = position.reference_after(ChessMove::new(from, to, MoveKind::Quiet))
    else {
        return false;
    };
    !is_square_attacked(&intermediate, to, attacker)
}

fn en_passant_has_capturable_pawn(position: &Position, us: Color, target: Square) -> bool {
    let rank = match us {
        Color::White => target.rank().checked_sub(1),
        Color::Black => target.rank().checked_add(1),
    };
    let Some(rank) = rank else {
        return false;
    };
    let Some(captured) = Square::from_file_rank(target.file(), rank) else {
        return false;
    };
    position.piece_at(captured) == Some(Piece::new(us.opposite(), PieceKind::Pawn))
}

fn pawn_forward(square: Square, color: Color, steps: i8) -> Option<Square> {
    let delta = match color {
        Color::White => steps,
        Color::Black => -steps,
    };
    let rank = square.rank() as i8 + delta;
    if !(0..8).contains(&rank) {
        return None;
    }
    Square::from_file_rank(square.file(), rank as u8)
}

fn square(file: u8, rank: u8) -> Square {
    Square::from_file_rank(file, rank).expect("constant board coordinate")
}

#[cfg(test)]
mod tests {
    use crate::{
        MoveKind, Position, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
        has_legal_move_mut,
    };

    #[test]
    fn start_position_has_twenty_legal_moves() {
        assert_eq!(Position::startpos().legal_moves().len(), 20);
    }

    #[test]
    fn mutable_generator_restores_position_exactly() {
        let mut position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid position");
        let before = position.clone();
        let moves = generate_legal_moves_mut(&mut position);
        assert_eq!(moves.len(), 48);
        assert_eq!(position, before);
    }

    #[test]
    fn legal_existence_probe_matches_full_generation_and_restores_position() {
        let fens = [
            crate::STARTPOS_FEN,
            "7k/8/8/8/8/8/8/K7 w - - 0 1",
            "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
            "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        ];

        for fen in fens {
            let mut probe_position = Position::from_fen(fen).expect("valid probe FEN");
            let original = probe_position.clone();
            let mut full_position = original.clone();
            let expected = !generate_legal_moves_mut(&mut full_position).is_empty();
            assert_eq!(has_legal_move_mut(&mut probe_position), expected, "{fen}");
            assert_eq!(probe_position, original, "probe must restore {fen}");
            assert_eq!(full_position, original, "full generator must restore {fen}");
        }
    }

    #[test]
    fn tactical_generator_matches_full_generator_filtered_to_tactical_moves() {
        let fens = [
            crate::STARTPOS_FEN,
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
            "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
            "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        ];

        for fen in fens {
            let mut full_position = Position::from_fen(fen).expect("valid comparison FEN");
            let mut tactical_position = full_position.clone();
            let mut expected: Vec<_> = generate_legal_moves_mut(&mut full_position)
                .as_slice()
                .iter()
                .copied()
                .filter(|mv| mv.kind().is_capture() || mv.kind().is_promotion())
                .collect();
            let mut actual = generate_legal_tactical_moves_mut(&mut tactical_position)
                .as_slice()
                .to_vec();
            expected.sort_unstable_by_key(|mv| mv.raw());
            actual.sort_unstable_by_key(|mv| mv.raw());

            assert_eq!(actual, expected, "tactical mismatch for {fen}");
            assert_eq!(full_position, Position::from_fen(fen).expect("valid FEN"));
            assert_eq!(
                tactical_position,
                Position::from_fen(fen).expect("valid FEN")
            );
        }
    }

    #[test]
    fn castling_moves_are_generated_when_paths_are_safe() {
        let position =
            Position::from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1").expect("valid position");
        let castles = position
            .legal_moves()
            .iter()
            .filter(|mv| matches!(mv.kind(), MoveKind::KingCastle | MoveKind::QueenCastle))
            .count();
        assert_eq!(castles, 2);
    }

    #[test]
    fn en_passant_and_promotions_are_semantic_move_kinds() {
        let en_passant = Position::from_fen("8/8/8/3pP3/8/8/8/K6k w - d6 0 1")
            .expect("valid en-passant position");
        assert!(
            en_passant
                .legal_moves()
                .iter()
                .any(|mv| mv.kind() == MoveKind::EnPassant)
        );

        let promotion =
            Position::from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1").expect("valid promotion position");
        assert_eq!(
            promotion
                .legal_moves()
                .iter()
                .filter(|mv| mv.kind().is_promotion())
                .count(),
            4
        );
    }
}
