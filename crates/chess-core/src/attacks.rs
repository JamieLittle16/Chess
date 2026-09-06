use crate::{Bitboard, Color, PieceKind, Position, Square};

const KNIGHT_DELTAS: [(i8, i8); 8] = [
    (1, 2),
    (2, 1),
    (2, -1),
    (1, -2),
    (-1, -2),
    (-2, -1),
    (-2, 1),
    (-1, 2),
];

const KING_DELTAS: [(i8, i8); 8] = [
    (1, 0),
    (1, 1),
    (0, 1),
    (-1, 1),
    (-1, 0),
    (-1, -1),
    (0, -1),
    (1, -1),
];

const BISHOP_DIRECTIONS: [(i8, i8); 4] = [(1, 1), (-1, 1), (1, -1), (-1, -1)];
const ROOK_DIRECTIONS: [(i8, i8); 4] = [(1, 0), (-1, 0), (0, 1), (0, -1)];
const BISHOP_DIRECTION_INCREASES_INDEX: [bool; 4] = [true, true, false, false];
const ROOK_DIRECTION_INCREASES_INDEX: [bool; 4] = [true, false, true, false];

// Fixed attack geometry is generated once at compile time. Leapers need one indexed load. Sliders
// use one precomputed ray per direction and clip it at the nearest occupied square, avoiding the
// coordinate arithmetic/bounds loop previously repeated for every traversed square.
const PAWN_ATTACKS: [[u64; 64]; 2] = generate_pawn_attacks();
const KNIGHT_ATTACKS: [u64; 64] = generate_leaper_attacks(&KNIGHT_DELTAS);
const KING_ATTACKS: [u64; 64] = generate_leaper_attacks(&KING_DELTAS);
const BISHOP_RAYS: [[u64; 64]; 4] = generate_slider_rays(&BISHOP_DIRECTIONS);
const ROOK_RAYS: [[u64; 64]; 4] = generate_slider_rays(&ROOK_DIRECTIONS);

#[must_use]
#[inline]
pub fn pawn_attacks(color: Color, square: Square) -> Bitboard {
    Bitboard::from_raw(PAWN_ATTACKS[color.index()][usize::from(square.index())])
}

#[must_use]
#[inline]
pub fn knight_attacks(square: Square) -> Bitboard {
    Bitboard::from_raw(KNIGHT_ATTACKS[usize::from(square.index())])
}

#[must_use]
#[inline]
pub fn king_attacks(square: Square) -> Bitboard {
    Bitboard::from_raw(KING_ATTACKS[usize::from(square.index())])
}

#[must_use]
#[inline]
pub fn bishop_attacks(square: Square, occupied: Bitboard) -> Bitboard {
    slider_attacks(
        square,
        occupied,
        &BISHOP_RAYS,
        &BISHOP_DIRECTION_INCREASES_INDEX,
    )
}

#[must_use]
#[inline]
pub fn rook_attacks(square: Square, occupied: Bitboard) -> Bitboard {
    slider_attacks(
        square,
        occupied,
        &ROOK_RAYS,
        &ROOK_DIRECTION_INCREASES_INDEX,
    )
}

#[must_use]
#[inline]
pub fn queen_attacks(square: Square, occupied: Bitboard) -> Bitboard {
    bishop_attacks(square, occupied) | rook_attacks(square, occupied)
}

/// Whether `square` is currently attacked by `attacker`.
///
/// This is occupancy-aware and intentionally independent of move generation so it can be used by
/// legality checks, castling validation, and later differential tests.
#[must_use]
pub fn is_square_attacked(position: &Position, square: Square, attacker: Color) -> bool {
    let occupied = position.occupied();

    if !(pawn_attacks(attacker.opposite(), square) & position.pieces(attacker, PieceKind::Pawn))
        .is_empty()
    {
        return true;
    }
    if !(knight_attacks(square) & position.pieces(attacker, PieceKind::Knight)).is_empty() {
        return true;
    }
    if !(king_attacks(square) & position.pieces(attacker, PieceKind::King)).is_empty() {
        return true;
    }

    let bishops_and_queens =
        position.pieces(attacker, PieceKind::Bishop) | position.pieces(attacker, PieceKind::Queen);
    if !(bishop_attacks(square, occupied) & bishops_and_queens).is_empty() {
        return true;
    }

    let rooks_and_queens =
        position.pieces(attacker, PieceKind::Rook) | position.pieces(attacker, PieceKind::Queen);
    !(rook_attacks(square, occupied) & rooks_and_queens).is_empty()
}

const fn generate_pawn_attacks() -> [[u64; 64]; 2] {
    let mut table = [[0_u64; 64]; 2];
    let mut square = 0_usize;
    while square < 64 {
        table[Color::White as usize][square] =
            offset_mask(square, -1, 1) | offset_mask(square, 1, 1);
        table[Color::Black as usize][square] =
            offset_mask(square, -1, -1) | offset_mask(square, 1, -1);
        square += 1;
    }
    table
}

const fn generate_leaper_attacks(deltas: &[(i8, i8)]) -> [u64; 64] {
    let mut table = [0_u64; 64];
    let mut square = 0_usize;
    while square < 64 {
        let mut mask = 0_u64;
        let mut delta = 0_usize;
        while delta < deltas.len() {
            mask |= offset_mask(square, deltas[delta].0, deltas[delta].1);
            delta += 1;
        }
        table[square] = mask;
        square += 1;
    }
    table
}

const fn generate_slider_rays(directions: &[(i8, i8); 4]) -> [[u64; 64]; 4] {
    let mut rays = [[0_u64; 64]; 4];
    let mut direction = 0_usize;
    while direction < directions.len() {
        let (file_delta, rank_delta) = directions[direction];
        let mut square = 0_usize;
        while square < 64 {
            let mut file = (square & 7) as i8 + file_delta;
            let mut rank = (square >> 3) as i8 + rank_delta;
            let mut ray = 0_u64;
            while file >= 0 && file < 8 && rank >= 0 && rank < 8 {
                ray |= 1_u64 << ((rank as u32) * 8 + file as u32);
                file += file_delta;
                rank += rank_delta;
            }
            rays[direction][square] = ray;
            square += 1;
        }
        direction += 1;
    }
    rays
}

const fn offset_mask(square: usize, file_delta: i8, rank_delta: i8) -> u64 {
    let file = (square & 7) as i8 + file_delta;
    let rank = (square >> 3) as i8 + rank_delta;
    if file < 0 || file >= 8 || rank < 0 || rank >= 8 {
        0
    } else {
        1_u64 << ((rank as u32) * 8 + file as u32)
    }
}

#[inline]
fn slider_attacks(
    square: Square,
    occupied: Bitboard,
    rays: &[[u64; 64]; 4],
    direction_increases_index: &[bool; 4],
) -> Bitboard {
    let square = usize::from(square.index());
    let occupied = occupied.raw();
    let mut attacks = 0_u64;
    let mut direction = 0_usize;

    while direction < 4 {
        let ray = rays[direction][square];
        let blockers = ray & occupied;
        if blockers == 0 {
            attacks |= ray;
        } else {
            let blocker = if direction_increases_index[direction] {
                blockers.trailing_zeros() as usize
            } else {
                (63 - blockers.leading_zeros()) as usize
            };
            // The blocker ray is a suffix of the origin ray. Removing that suffix retains every
            // square through the first blocker itself, exactly matching ordinary slider semantics.
            attacks |= ray ^ rays[direction][blocker];
        }
        direction += 1;
    }

    Bitboard::from_raw(attacks)
}

#[cfg(test)]
mod tests {
    use crate::{Bitboard, Color, Position, Square};

    use super::{
        BISHOP_DIRECTIONS, KING_DELTAS, KNIGHT_DELTAS, ROOK_DIRECTIONS, bishop_attacks,
        is_square_attacked, king_attacks, knight_attacks, pawn_attacks, rook_attacks,
    };

    #[test]
    fn precomputed_fixed_attacks_match_coordinate_reference_exhaustively() {
        for index in 0..64 {
            let square = Square::from_index(index).expect("board square");
            assert_eq!(
                knight_attacks(square),
                reference_leaper_attacks(square, &KNIGHT_DELTAS)
            );
            assert_eq!(
                king_attacks(square),
                reference_leaper_attacks(square, &KING_DELTAS)
            );
            assert_eq!(
                pawn_attacks(Color::White, square),
                reference_leaper_attacks(square, &[(-1, 1), (1, 1)])
            );
            assert_eq!(
                pawn_attacks(Color::Black, square),
                reference_leaper_attacks(square, &[(-1, -1), (1, -1)])
            );
        }
    }

    #[test]
    fn clipped_slider_rays_match_coordinate_reference_on_dense_occupancy_sample() {
        let mut state = 0x9e37_79b9_7f4a_7c15_u64;
        for index in 0..64 {
            let square = Square::from_index(index).expect("board square");
            for _ in 0..512 {
                // Deterministic xorshift sample includes unrelated blockers and multiple blockers
                // on the same ray. Empty/full boards are checked separately below.
                state ^= state << 13;
                state ^= state >> 7;
                state ^= state << 17;
                let occupied = Bitboard::from_raw(state);
                assert_eq!(
                    bishop_attacks(square, occupied),
                    reference_slider_attacks(square, occupied, &BISHOP_DIRECTIONS)
                );
                assert_eq!(
                    rook_attacks(square, occupied),
                    reference_slider_attacks(square, occupied, &ROOK_DIRECTIONS)
                );
            }
            for occupied in [Bitboard::EMPTY, Bitboard::FULL] {
                assert_eq!(
                    bishop_attacks(square, occupied),
                    reference_slider_attacks(square, occupied, &BISHOP_DIRECTIONS)
                );
                assert_eq!(
                    rook_attacks(square, occupied),
                    reference_slider_attacks(square, occupied, &ROOK_DIRECTIONS)
                );
            }
        }
    }

    #[test]
    fn leapers_respect_board_edges() {
        let a1 = Square::from_file_rank(0, 0).expect("a1");
        let b3 = Square::from_file_rank(1, 2).expect("b3");
        let c2 = Square::from_file_rank(2, 1).expect("c2");
        let b1 = Square::from_file_rank(1, 0).expect("b1");
        let a2 = Square::from_file_rank(0, 1).expect("a2");
        let b2 = Square::from_file_rank(1, 1).expect("b2");

        let knight = knight_attacks(a1);
        assert_eq!(knight.count(), 2);
        assert!(knight.contains(b3));
        assert!(knight.contains(c2));

        let king = king_attacks(a1);
        assert_eq!(king.count(), 3);
        assert!(king.contains(b1));
        assert!(king.contains(a2));
        assert!(king.contains(b2));
    }

    #[test]
    fn pawn_attacks_are_directional() {
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let c5 = Square::from_file_rank(2, 4).expect("c5");
        let e5 = Square::from_file_rank(4, 4).expect("e5");
        let c3 = Square::from_file_rank(2, 2).expect("c3");
        let e3 = Square::from_file_rank(4, 2).expect("e3");

        let white = pawn_attacks(Color::White, d4);
        assert_eq!(white.count(), 2);
        assert!(white.contains(c5));
        assert!(white.contains(e5));

        let black = pawn_attacks(Color::Black, d4);
        assert_eq!(black.count(), 2);
        assert!(black.contains(c3));
        assert!(black.contains(e3));
    }

    #[test]
    fn slider_includes_first_blocker_and_stops() {
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let f6 = Square::from_file_rank(5, 5).expect("f6");
        let g7 = Square::from_file_rank(6, 6).expect("g7");
        let occupied = Bitboard::EMPTY.with(f6);
        let attacks = bishop_attacks(d4, occupied);

        assert!(attacks.contains(f6));
        assert!(!attacks.contains(g7));
    }

    #[test]
    fn attack_query_uses_position_occupancy() {
        let position = Position::startpos();
        let e3 = Square::from_file_rank(4, 2).expect("e3");
        let e4 = Square::from_file_rank(4, 3).expect("e4");
        assert!(is_square_attacked(&position, e3, Color::White));
        assert!(!is_square_attacked(&position, e4, Color::White));
    }

    fn reference_leaper_attacks(square: Square, deltas: &[(i8, i8)]) -> Bitboard {
        let mut attacks = Bitboard::EMPTY;
        for &(file_delta, rank_delta) in deltas {
            let file = square.file() as i8 + file_delta;
            let rank = square.rank() as i8 + rank_delta;
            if (0..8).contains(&file)
                && (0..8).contains(&rank)
                && let Some(target) = Square::from_file_rank(file as u8, rank as u8)
            {
                attacks = attacks.with(target);
            }
        }
        attacks
    }

    fn reference_slider_attacks(
        square: Square,
        occupied: Bitboard,
        directions: &[(i8, i8)],
    ) -> Bitboard {
        let mut attacks = Bitboard::EMPTY;
        for &(file_delta, rank_delta) in directions {
            let mut file = square.file() as i8 + file_delta;
            let mut rank = square.rank() as i8 + rank_delta;
            while (0..8).contains(&file) && (0..8).contains(&rank) {
                let target = Square::from_file_rank(file as u8, rank as u8).expect("on board");
                attacks = attacks.with(target);
                if occupied.contains(target) {
                    break;
                }
                file += file_delta;
                rank += rank_delta;
            }
        }
        attacks
    }
}
