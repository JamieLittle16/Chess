//! Transparent classical evaluation used as the permanent reference baseline.
//!
//! M4 E5 tests a compact king-safety term on top of the accepted tapered geometric PSQT. Runtime
//! evaluation remains allocation-free. The safety model deliberately stays small: a local king
//! zone measures direct enemy piece pressure while a short pawn-shield term rewards intact cover
//! only while the king remains near its home rank. Both signals are middle-game only and therefore
//! disappear naturally as tapered phase reaches the endgame.

use chess_core::{
    Bitboard, Color, PieceKind, Position, bishop_attacks, king_attacks, knight_attacks, pawn_attacks,
    queen_attacks, rook_attacks,
};

/// Conventional centipawn-like material values retained from the material-only reference.
pub const PIECE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

const PHASE_WEIGHTS: [i32; 6] = [0, 1, 1, 2, 4, 0];
const MAX_PHASE: i32 = 24;
const MG_PSQT: [[i16; 64]; 6] = generate_psqt(false);
const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);

// King-zone pressure uses attack-square hits rather than legal moves. Heavier pieces are weighted
// more strongly because a rook/queen entering the king zone is more forcing than one minor-piece
// attack. The final multiplier converts compact attack units into centipawn-like MG pressure.
const PAWN_KING_ATTACK_UNIT: i32 = 3;
const KNIGHT_KING_ATTACK_UNIT: i32 = 5;
const BISHOP_KING_ATTACK_UNIT: i32 = 4;
const ROOK_KING_ATTACK_UNIT: i32 = 6;
const QUEEN_KING_ATTACK_UNIT: i32 = 8;
const KING_PRESSURE_CP_PER_UNIT: i32 = 2;
const FIRST_SHIELD_PAWN_BONUS: i32 = 10;
const SECOND_SHIELD_PAWN_BONUS: i32 = 4;

/// Return the material owned by one side in centipawn-like units.
#[must_use]
pub fn material(position: &Position, color: Color) -> i32 {
    PieceKind::ALL
        .into_iter()
        .map(|kind| position.pieces(color, kind).count() as i32 * PIECE_VALUES[kind.index()])
        .sum()
}

/// Evaluate a position from the side-to-move perspective.
///
/// Positive values favour the player to move; negative values favour their opponent. The tapered
/// score interpolates between middle-game and end-game positional preferences using remaining
/// non-pawn material. Black reuses the same PSQT tables by vertically mirroring each square.
#[must_use]
pub fn evaluate(position: &Position) -> i32 {
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let mut phase = 0_i32;
    let occupied = position.occupied();

    for color in Color::ALL {
        let sign = if color == Color::White { 1 } else { -1 };
        middle_game += sign * king_safety_middle_game(position, color, occupied);

        for kind in PieceKind::ALL {
            let mut pieces = position.pieces(color, kind);
            let count = pieces.count() as i32;
            let material = count * PIECE_VALUES[kind.index()];
            middle_game += sign * material;
            end_game += sign * material;
            phase += count * PHASE_WEIGHTS[kind.index()];

            while let Some(square) = pieces.pop_lsb() {
                let relative_index = relative_square_index(color, square.file(), square.rank());
                middle_game += sign * i32::from(MG_PSQT[kind.index()][relative_index]);
                end_game += sign * i32::from(EG_PSQT[kind.index()][relative_index]);
            }
        }
    }

    let phase = phase.min(MAX_PHASE);
    let white_minus_black = (middle_game * phase + end_game * (MAX_PHASE - phase)) / MAX_PHASE;
    match position.side_to_move() {
        Color::White => white_minus_black,
        Color::Black => -white_minus_black,
    }
}

fn king_safety_middle_game(position: &Position, color: Color, occupied: Bitboard) -> i32 {
    let Some(king) = position.pieces(color, PieceKind::King).into_iter().next() else {
        return 0;
    };
    let zone = king_attacks(king).with(king);
    let enemy = color.opposite();
    let mut pressure_units = 0_i32;

    for square in position.pieces(enemy, PieceKind::Pawn) {
        pressure_units += i32::try_from((pawn_attacks(enemy, square) & zone).count())
            .expect("king-zone hit count fits i32")
            * PAWN_KING_ATTACK_UNIT;
    }
    for square in position.pieces(enemy, PieceKind::Knight) {
        pressure_units += i32::try_from((knight_attacks(square) & zone).count())
            .expect("king-zone hit count fits i32")
            * KNIGHT_KING_ATTACK_UNIT;
    }
    for square in position.pieces(enemy, PieceKind::Bishop) {
        pressure_units += i32::try_from((bishop_attacks(square, occupied) & zone).count())
            .expect("king-zone hit count fits i32")
            * BISHOP_KING_ATTACK_UNIT;
    }
    for square in position.pieces(enemy, PieceKind::Rook) {
        pressure_units += i32::try_from((rook_attacks(square, occupied) & zone).count())
            .expect("king-zone hit count fits i32")
            * ROOK_KING_ATTACK_UNIT;
    }
    for square in position.pieces(enemy, PieceKind::Queen) {
        pressure_units += i32::try_from((queen_attacks(square, occupied) & zone).count())
            .expect("king-zone hit count fits i32")
            * QUEEN_KING_ATTACK_UNIT;
    }

    pawn_shield_bonus(position, color, king.file(), king.rank())
        - pressure_units * KING_PRESSURE_CP_PER_UNIT
}

fn pawn_shield_bonus(position: &Position, color: Color, king_file: u8, king_rank: u8) -> i32 {
    let relative_rank = match color {
        Color::White => king_rank,
        Color::Black => 7 - king_rank,
    };
    if relative_rank > 1 {
        return 0;
    }

    let own_pawns = position.pieces(color, PieceKind::Pawn);
    let mut bonus = 0_i32;
    let first_rank = match color {
        Color::White => king_rank.checked_add(1),
        Color::Black => king_rank.checked_sub(1),
    };
    let second_rank = match color {
        Color::White => king_rank.checked_add(2),
        Color::Black => king_rank.checked_sub(2),
    };

    let first_file = king_file.saturating_sub(1);
    let last_file = king_file.saturating_add(1).min(7);
    let mut file = first_file;
    while file <= last_file {
        if let Some(rank) = first_rank
            && rank < 8
            && let Some(square) = chess_core::Square::from_file_rank(file, rank)
            && own_pawns.contains(square)
        {
            bonus += FIRST_SHIELD_PAWN_BONUS;
        } else if let Some(rank) = second_rank
            && rank < 8
            && let Some(square) = chess_core::Square::from_file_rank(file, rank)
            && own_pawns.contains(square)
        {
            bonus += SECOND_SHIELD_PAWN_BONUS;
        }
        if file == last_file {
            break;
        }
        file += 1;
    }
    bonus
}

#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {
    let relative_rank = match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    };
    (relative_rank as usize) * 8 + file as usize
}

const fn generate_psqt(end_game: bool) -> [[i16; 64]; 6] {
    let mut tables = [[0_i16; 64]; 6];
    let mut piece = 0_usize;
    while piece < 6 {
        let mut index = 0_usize;
        while index < 64 {
            let file = (index & 7) as i32;
            let rank = (index >> 3) as i32;
            tables[piece][index] = geometric_bonus(piece, file, rank, end_game) as i16;
            index += 1;
        }
        piece += 1;
    }
    tables
}

const fn geometric_bonus(piece: usize, file: i32, rank: i32, end_game: bool) -> i32 {
    let doubled_file = file * 2;
    let doubled_rank = rank * 2;
    let file_distance = abs_i32(doubled_file - 7);
    let rank_distance = abs_i32(doubled_rank - 7);
    let centre = 14 - file_distance - rank_distance;
    let file_centrality = 7 - file_distance;

    match piece {
        0 => {
            let advance = if end_game {
                match rank {
                    0 | 1 => 0,
                    2 => 8,
                    3 => 16,
                    4 => 30,
                    5 => 50,
                    6 => 80,
                    _ => 0,
                }
            } else {
                match rank {
                    0 | 1 => 0,
                    2 => 5,
                    3 => 10,
                    4 => 20,
                    5 => 35,
                    6 => 60,
                    _ => 0,
                }
            };
            advance + file_centrality / 2
        }
        1 => {
            if end_game {
                centre * 3 - 18
            } else {
                centre * 4 - 24
            }
        }
        2 => {
            if end_game {
                centre * 2 - 6
            } else {
                centre * 2 - 8
            }
        }
        3 => {
            let seventh = if rank == 6 { 14 } else { 0 };
            if end_game {
                seventh + rank * 2
            } else {
                seventh + rank
            }
        }
        4 => {
            if end_game {
                centre * 2 - 8
            } else {
                centre - 8
            }
        }
        5 => {
            if end_game {
                centre * 4 - 24
            } else {
                let home = if rank == 0 { 12 } else { -rank * 10 };
                let castle = if rank == 0 && (file == 2 || file == 6) {
                    20
                } else {
                    0
                };
                home + castle - centre * 2
            }
        }
        _ => 0,
    }
}

const fn abs_i32(value: i32) -> i32 {
    if value < 0 { -value } else { value }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position};

    use super::{evaluate, king_safety_middle_game};

    #[test]
    fn starting_position_is_positionally_equal() {
        assert_eq!(evaluate(&Position::startpos()), 0);
    }

    #[test]
    fn score_is_from_side_to_move_perspective() {
        let white = Position::from_fen("7k/8/8/8/8/8/8/Q6K w - - 0 1").expect("valid FEN");
        let black = Position::from_fen("7k/8/8/8/8/8/8/Q6K b - - 0 1").expect("valid FEN");
        assert_eq!(evaluate(&white), -evaluate(&black));
        assert!(evaluate(&white) > 800);
    }

    #[test]
    fn central_knight_is_preferred_to_corner_knight() {
        let central = Position::from_fen("7k/8/8/8/3N4/8/8/7K w - - 0 1").expect("valid FEN");
        let corner = Position::from_fen("7k/8/8/8/8/8/8/N6K w - - 0 1").expect("valid FEN");
        assert!(evaluate(&central) > evaluate(&corner));
    }

    #[test]
    fn advanced_pawn_is_rewarded_in_the_endgame() {
        let advanced = Position::from_fen("7k/4P3/8/8/8/8/8/7K w - - 0 1").expect("valid FEN");
        let homeward = Position::from_fen("7k/8/8/8/8/8/4P3/7K w - - 0 1").expect("valid FEN");
        assert!(evaluate(&advanced) > evaluate(&homeward));
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {
        let central = Position::from_fen("7k/8/8/8/3K4/8/8/8 w - - 0 1").expect("valid FEN");
        let corner = Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        assert!(evaluate(&central) > evaluate(&corner));
    }

    #[test]
    fn intact_home_rank_pawn_cover_receives_a_shield_bonus() {
        let shielded = Position::from_fen("7k/8/8/8/8/8/5PPP/6K1 w - - 0 1").expect("valid FEN");
        let exposed = Position::from_fen("7k/8/8/8/8/8/8/6K1 w - - 0 1").expect("valid FEN");
        assert!(
            king_safety_middle_game(&shielded, Color::White, shielded.occupied())
                > king_safety_middle_game(&exposed, Color::White, exposed.occupied())
        );
    }

    #[test]
    fn direct_heavy_piece_pressure_penalises_the_king_zone() {
        let pressured = Position::from_fen("6r1/7k/8/8/8/8/8/6K1 w - - 0 1").expect("valid FEN");
        assert!(king_safety_middle_game(&pressured, Color::White, pressured.occupied()) < 0);
    }
}
