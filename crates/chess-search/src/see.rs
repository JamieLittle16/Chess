use chess_core::{
    Bitboard, ChessMove, Color, MoveKind, PieceKind, Position, Square, bishop_attacks,
    king_attacks, knight_attacks, pawn_attacks, rook_attacks,
};

const SEE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 20_000];
const MAX_EXCHANGES: usize = 32;

/// Static exchange value of one legal tactical move in centipawn-like material units.
///
/// The exchange sequence is evaluated on local bitboards only. Potential recaptures are filtered by
/// king safety against the local post-capture occupancy, so pinned recaptures do not make a sound
/// capture look artificially bad. Promotions and en-passant are handled explicitly. This routine is
/// search infrastructure: it does not mutate `Position` and performs no heap allocation.
pub(super) fn see(position: &Position, mv: ChessMove) -> i32 {
    let Some(moving) = position.piece_at(mv.from()) else {
        return 0;
    };
    let us = moving.color();
    let them = us.opposite();
    let target = mv.to();

    let mut boards = [[0_u64; 6]; 2];
    for color in Color::ALL {
        for kind in PieceKind::ALL {
            boards[color.index()][kind.index()] = position.pieces(color, kind).raw();
        }
    }

    let capture = captured_piece(position, mv, us);
    let captured_value = capture.map_or(0, |(kind, _)| SEE_VALUES[kind.index()]);
    let promoted_kind = mv.kind().promotion_piece();
    let promotion_gain = promoted_kind.map_or(0, |kind| {
        SEE_VALUES[kind.index()] - SEE_VALUES[PieceKind::Pawn.index()]
    });

    let from_bit = mv.from().bit();
    let target_bit = target.bit();
    boards[us.index()][moving.kind().index()] &= !from_bit;
    if let Some((kind, square)) = capture {
        boards[them.index()][kind.index()] &= !square.bit();
    }
    let resulting_kind = promoted_kind.unwrap_or(moving.kind());
    boards[us.index()][resulting_kind.index()] |= target_bit;

    let mut occupied = position.occupied().raw() & !from_bit;
    if let Some((_, square)) = capture {
        occupied &= !square.bit();
    }
    occupied |= target_bit;

    let mut gains = [0_i32; MAX_EXCHANGES];
    gains[0] = captured_value + promotion_gain;
    let mut depth = 0_usize;
    let mut side = them;
    let mut occupant_side = us;
    let mut occupant_kind = resulting_kind;

    while depth + 1 < MAX_EXCHANGES {
        let Some(attacker) = least_legal_attacker(
            target,
            side,
            occupant_side,
            occupant_kind,
            occupied,
            &boards,
        ) else {
            break;
        };

        depth += 1;
        let promotion_gain =
            if attacker.kind == PieceKind::Pawn && pawn_promotes_on(side, target.rank()) {
                SEE_VALUES[PieceKind::Queen.index()] - SEE_VALUES[PieceKind::Pawn.index()]
            } else {
                0
            };
        gains[depth] = SEE_VALUES[occupant_kind.index()] + promotion_gain - gains[depth - 1];

        boards[occupant_side.index()][occupant_kind.index()] &= !target_bit;
        boards[side.index()][attacker.kind.index()] &= !attacker.square.bit();
        boards[side.index()][attacker.resulting_kind.index()] |= target_bit;
        occupied &= !attacker.square.bit();

        occupant_side = side;
        occupant_kind = attacker.resulting_kind;
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
    resulting_kind: PieceKind,
}

fn least_legal_attacker(
    target: Square,
    side: Color,
    occupant_side: Color,
    occupant_kind: PieceKind,
    occupied: u64,
    boards: &[[u64; 6]; 2],
) -> Option<Attacker> {
    let attack_sets = [
        (
            PieceKind::Pawn,
            pawn_attacks(side.opposite(), target).raw()
                & boards[side.index()][PieceKind::Pawn.index()],
        ),
        (
            PieceKind::Knight,
            knight_attacks(target).raw() & boards[side.index()][PieceKind::Knight.index()],
        ),
        (
            PieceKind::Bishop,
            bishop_attacks(target, Bitboard::from_raw(occupied)).raw()
                & boards[side.index()][PieceKind::Bishop.index()],
        ),
        (
            PieceKind::Rook,
            rook_attacks(target, Bitboard::from_raw(occupied)).raw()
                & boards[side.index()][PieceKind::Rook.index()],
        ),
        (
            PieceKind::Queen,
            (bishop_attacks(target, Bitboard::from_raw(occupied)).raw()
                | rook_attacks(target, Bitboard::from_raw(occupied)).raw())
                & boards[side.index()][PieceKind::Queen.index()],
        ),
        (
            PieceKind::King,
            king_attacks(target).raw() & boards[side.index()][PieceKind::King.index()],
        ),
    ];

    for (kind, mut candidates) in attack_sets {
        while candidates != 0 {
            let index = candidates.trailing_zeros() as u8;
            candidates &= candidates - 1;
            let square = Square::from_index(index).expect("bit index is on board");
            let resulting_kind = if kind == PieceKind::Pawn && pawn_promotes_on(side, target.rank())
            {
                PieceKind::Queen
            } else {
                kind
            };
            if capture_keeps_king_safe(
                target,
                side,
                occupant_side,
                occupant_kind,
                square,
                kind,
                resulting_kind,
                occupied,
                boards,
            ) {
                return Some(Attacker {
                    square,
                    kind,
                    resulting_kind,
                });
            }
        }
    }
    None
}

#[allow(clippy::too_many_arguments)]
fn capture_keeps_king_safe(
    target: Square,
    side: Color,
    occupant_side: Color,
    occupant_kind: PieceKind,
    attacker_square: Square,
    attacker_kind: PieceKind,
    resulting_kind: PieceKind,
    occupied: u64,
    boards: &[[u64; 6]; 2],
) -> bool {
    let mut next = *boards;
    next[occupant_side.index()][occupant_kind.index()] &= !target.bit();
    next[side.index()][attacker_kind.index()] &= !attacker_square.bit();
    next[side.index()][resulting_kind.index()] |= target.bit();
    let next_occupied = occupied & !attacker_square.bit();

    let kings = next[side.index()][PieceKind::King.index()];
    if kings.count_ones() != 1 {
        return false;
    }
    let king_index = kings.trailing_zeros() as u8;
    let king = Square::from_index(king_index).expect("king bit is on board");
    !square_attacked(king, side.opposite(), next_occupied, &next)
}

fn square_attacked(target: Square, attacker: Color, occupied: u64, boards: &[[u64; 6]; 2]) -> bool {
    let side = attacker.index();
    if pawn_attacks(attacker.opposite(), target).raw() & boards[side][PieceKind::Pawn.index()] != 0
    {
        return true;
    }
    if knight_attacks(target).raw() & boards[side][PieceKind::Knight.index()] != 0 {
        return true;
    }
    if king_attacks(target).raw() & boards[side][PieceKind::King.index()] != 0 {
        return true;
    }
    let occupied = Bitboard::from_raw(occupied);
    if bishop_attacks(target, occupied).raw()
        & (boards[side][PieceKind::Bishop.index()] | boards[side][PieceKind::Queen.index()])
        != 0
    {
        return true;
    }
    rook_attacks(target, occupied).raw()
        & (boards[side][PieceKind::Rook.index()] | boards[side][PieceKind::Queen.index()])
        != 0
}

fn captured_piece(position: &Position, mv: ChessMove, us: Color) -> Option<(PieceKind, Square)> {
    if mv.kind() == MoveKind::EnPassant {
        let rank = match us {
            Color::White => mv.to().rank().checked_sub(1)?,
            Color::Black => mv.to().rank().checked_add(1)?,
        };
        let square = Square::from_file_rank(mv.to().file(), rank)?;
        Some((PieceKind::Pawn, square))
    } else {
        position
            .piece_at(mv.to())
            .map(|piece| (piece.kind(), mv.to()))
    }
}

#[inline]
const fn pawn_promotes_on(color: Color, rank: u8) -> bool {
    match color {
        Color::White => rank == 7,
        Color::Black => rank == 0,
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{MoveKind, Position, Square};

    use super::see;

    #[test]
    fn hanging_queen_capture_is_strongly_positive() {
        let position = Position::from_fen("7k/8/8/8/3q4/8/3R4/K7 w - - 0 1").expect("valid FEN");
        let d2 = Square::from_file_rank(3, 1).expect("d2");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.from() == d2 && mv.to() == d4)
            .expect("Rxd4 is legal");
        assert!(see(&position, mv) >= 800);
    }

    #[test]
    fn poisoned_queen_capture_is_negative() {
        let position = Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
        let d1 = Square::from_file_rank(3, 0).expect("d1");
        let d7 = Square::from_file_rank(3, 6).expect("d7");
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.from() == d1 && mv.to() == d7)
            .expect("Qxd7 is legal");
        assert!(see(&position, mv) < 0);
    }

    #[test]
    fn pinned_recapture_is_not_counted_as_legal() {
        let position =
            Position::from_fen("4k3/4n3/8/3q4/8/8/6B1/K3R3 w - - 0 1").expect("valid FEN");
        let g2 = Square::from_file_rank(6, 1).expect("g2");
        let d5 = Square::from_file_rank(3, 4).expect("d5");
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.from() == g2 && mv.to() == d5)
            .expect("Bxd5 is legal");
        assert!(see(&position, mv) >= 800);
    }

    #[test]
    fn en_passant_removes_the_off_target_captured_pawn() {
        let position = Position::from_fen("k7/8/8/4KPp1/8/8/8/8 w - g6 0 1").expect("valid FEN");
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.kind() == MoveKind::EnPassant)
            .expect("en-passant is legal");
        assert_eq!(see(&position, mv), 100);
    }

    #[test]
    fn quiet_promotion_counts_the_material_transformation() {
        let position = Position::from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        let mv = position
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.kind() == MoveKind::PromoteQueen)
            .expect("queen promotion is legal");
        assert_eq!(see(&position, mv), 800);
    }
}
