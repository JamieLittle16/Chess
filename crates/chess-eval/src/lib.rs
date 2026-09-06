//! Transparent classical evaluation used as the permanent reference baseline.
//!
//! M4 E2-safe extends tapered material/PSQT with cheap pawn-safe geometric mobility. Runtime
//! evaluation remains allocation-free: iterate existing piece bitboards, perform table
//! lookups/attack queries, and interpolate one middle-game/end-game score pair. Mobility deliberately
//! avoids legal move generation and make/unmake.

use chess_core::{
    Bitboard, Color, PieceKind, Position, Square, bishop_attacks, knight_attacks, pawn_attacks,
    queen_attacks, rook_attacks,
};

/// Conventional centipawn-like material values retained from the material-only reference.
pub const PIECE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

const PHASE_WEIGHTS: [i32; 6] = [0, 1, 1, 2, 4, 0];
const MAX_PHASE: i32 = 24;
const MG_PSQT: [[i16; 64]; 6] = generate_psqt(false);
const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);

// Keep the same E2-v1 weights so this experiment isolates the mobility-area hypothesis. Pawns and
// kings remain excluded: pawn structure and king safety are independent evaluation experiments.
const MG_MOBILITY_PER_SQUARE: [i32; 6] = [0, 4, 4, 2, 1, 0];
const EG_MOBILITY_PER_SQUARE: [i32; 6] = [0, 4, 5, 4, 2, 0];

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
        let own_occupied = color_occupied(position, color);
        let unsafe_by_pawn = pawn_attack_map(position, color.opposite());
        let mobility_area = !own_occupied & !unsafe_by_pawn;

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

                let mobility = mobility_count(kind, square, occupied, mobility_area);
                middle_game += sign * mobility * MG_MOBILITY_PER_SQUARE[kind.index()];
                end_game += sign * mobility * EG_MOBILITY_PER_SQUARE[kind.index()];
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

#[inline]
fn color_occupied(position: &Position, color: Color) -> Bitboard {
    let mut occupied = Bitboard::EMPTY;
    for kind in PieceKind::ALL {
        occupied = occupied | position.pieces(color, kind);
    }
    occupied
}

#[inline]
fn pawn_attack_map(position: &Position, color: Color) -> Bitboard {
    let mut attacks = Bitboard::EMPTY;
    for square in position.pieces(color, PieceKind::Pawn) {
        attacks = attacks | pawn_attacks(color, square);
    }
    attacks
}

#[inline]
fn mobility_count(
    kind: PieceKind,
    square: Square,
    occupied: Bitboard,
    mobility_area: Bitboard,
) -> i32 {
    let attacks = match kind {
        PieceKind::Knight => knight_attacks(square),
        PieceKind::Bishop => bishop_attacks(square, occupied),
        PieceKind::Rook => rook_attacks(square, occupied),
        PieceKind::Queen => queen_attacks(square, occupied),
        PieceKind::Pawn | PieceKind::King => return 0,
    };
    (attacks & mobility_area).count() as i32
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
    use chess_core::{Bitboard, Color, PieceKind, Position, Square};

    use super::{color_occupied, evaluate, mobility_count, pawn_attack_map};

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
    fn enemy_pawn_control_is_removed_from_knight_mobility() {
        let position = Position::from_fen("7k/8/4p3/8/3N4/8/8/7K w - - 0 1")
            .expect("valid FEN");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let own = color_occupied(&position, Color::White);
        let unsafe_by_pawn = pawn_attack_map(&position, Color::Black);
        let mobility_area = !own & !unsafe_by_pawn;
        assert_eq!(
            mobility_count(PieceKind::Knight, d4, position.occupied(), mobility_area),
            7
        );
    }

    #[test]
    fn bishop_mobility_excludes_own_blockers() {
        let position = Position::from_fen("7k/8/8/2P1P3/3B4/2P1P3/8/7K w - - 0 1")
            .expect("valid FEN");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let own = color_occupied(&position, Color::White);
        assert_eq!(
            mobility_count(
                PieceKind::Bishop,
                d4,
                position.occupied(),
                !own & Bitboard::FULL,
            ),
            0
        );
    }
}
