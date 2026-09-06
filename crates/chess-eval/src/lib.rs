//! Transparent classical evaluation used as the permanent reference baseline.
//!
//! M4 E3 candidate extends tapered material/PSQT with cheap pawn-structure terms. All structural
//! relations come from bitboards and compile-time masks; evaluation remains allocation-free and does
//! not generate moves.

use chess_core::{Bitboard, Color, PieceKind, Position, Square, pawn_attacks};

/// Conventional centipawn-like material values retained from the material-only reference.
pub const PIECE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

const PHASE_WEIGHTS: [i32; 6] = [0, 1, 1, 2, 4, 0];
const MAX_PHASE: i32 = 24;
const MG_PSQT: [[i16; 64]; 6] = generate_psqt(false);
const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);

const FILE_MASKS: [u64; 8] = generate_file_masks();
const ADJACENT_FILE_MASKS: [u64; 8] = generate_adjacent_file_masks();
const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();

const DOUBLED_PAWN_MG_PENALTY: i32 = 10;
const DOUBLED_PAWN_EG_PENALTY: i32 = 15;
const ISOLATED_PAWN_MG_PENALTY: i32 = 12;
const ISOLATED_PAWN_EG_PENALTY: i32 = 10;
const SUPPORTED_PAWN_MG_BONUS: i32 = 6;
const SUPPORTED_PAWN_EG_BONUS: i32 = 10;
const PHALANX_PAWN_MG_BONUS: i32 = 4;
const PHALANX_PAWN_EG_BONUS: i32 = 6;
const PASSED_PAWN_MG_BONUS: [i32; 8] = [0, 0, 0, 5, 12, 25, 45, 0];
const PASSED_PAWN_EG_BONUS: [i32; 8] = [0, 0, 0, 10, 25, 50, 90, 0];

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

    for color in Color::ALL {
        let sign = if color == Color::White { 1 } else { -1 };
        let (pawn_middle_game, pawn_end_game) = pawn_structure(position, color);
        middle_game += sign * pawn_middle_game;
        end_game += sign * pawn_end_game;

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

fn pawn_structure(position: &Position, color: Color) -> (i32, i32) {
    let pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    // Count each extra pawn on a file once. This avoids charging both members of a doubled pair the
    // full penalty and naturally extends to tripled pawns.
    for file_mask in FILE_MASKS {
        let count = (pawns.raw() & file_mask).count_ones() as i32;
        if count > 1 {
            let extras = count - 1;
            middle_game -= extras * DOUBLED_PAWN_MG_PENALTY;
            end_game -= extras * DOUBLED_PAWN_EG_PENALTY;
        }
    }

    for square in pawns {
        let file = usize::from(square.file());
        let relative_rank = relative_rank(color, square.rank());

        if pawns.raw() & ADJACENT_FILE_MASKS[file] == 0 {
            middle_game -= ISOLATED_PAWN_MG_PENALTY;
            end_game -= ISOLATED_PAWN_EG_PENALTY;
        }

        // Reversing the pawn direction around the target square gives exactly the two source
        // squares from which a friendly pawn would support this pawn.
        if !(pawn_attacks(color.opposite(), square) & pawns).is_empty() {
            middle_game += SUPPORTED_PAWN_MG_BONUS;
            end_game += SUPPORTED_PAWN_EG_BONUS;
        }

        if !(phalanx_mask(square) & pawns).is_empty() {
            middle_game += PHALANX_PAWN_MG_BONUS;
            end_game += PHALANX_PAWN_EG_BONUS;
        }

        let passed_mask = PASSED_PAWN_MASKS[color.index()][usize::from(square.index())];
        if enemy_pawns.raw() & passed_mask == 0 {
            middle_game += PASSED_PAWN_MG_BONUS[relative_rank];
            end_game += PASSED_PAWN_EG_BONUS[relative_rank];
        }
    }

    (middle_game, end_game)
}

#[inline]
fn phalanx_mask(square: Square) -> Bitboard {
    let file = square.file();
    let mut mask = 0_u64;
    if file > 0 {
        mask |= 1_u64 << (square.index() - 1);
    }
    if file < 7 {
        mask |= 1_u64 << (square.index() + 1);
    }
    Bitboard::from_raw(mask)
}

#[inline]
const fn relative_rank(color: Color, rank: u8) -> usize {
    match color {
        Color::White => rank as usize,
        Color::Black => (7 - rank) as usize,
    }
}

#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {
    relative_rank(color, rank) * 8 + file as usize
}

const fn generate_file_masks() -> [u64; 8] {
    let mut masks = [0_u64; 8];
    let mut file = 0_usize;
    while file < 8 {
        let mut rank = 0_usize;
        while rank < 8 {
            masks[file] |= 1_u64 << (rank * 8 + file);
            rank += 1;
        }
        file += 1;
    }
    masks
}

const fn generate_adjacent_file_masks() -> [u64; 8] {
    let files = generate_file_masks();
    let mut masks = [0_u64; 8];
    let mut file = 0_usize;
    while file < 8 {
        if file > 0 {
            masks[file] |= files[file - 1];
        }
        if file + 1 < 8 {
            masks[file] |= files[file + 1];
        }
        file += 1;
    }
    masks
}

const fn generate_passed_pawn_masks() -> [[u64; 64]; 2] {
    let mut masks = [[0_u64; 64]; 2];
    let mut square = 0_usize;
    while square < 64 {
        let file = (square & 7) as i8;
        let rank = (square >> 3) as i8;

        let mut target_rank = rank + 1;
        while target_rank < 8 {
            let mut target_file = file - 1;
            while target_file <= file + 1 {
                if target_file >= 0 && target_file < 8 {
                    masks[Color::White as usize][square] |=
                        1_u64 << ((target_rank as u32) * 8 + target_file as u32);
                }
                target_file += 1;
            }
            target_rank += 1;
        }

        let mut target_rank = rank - 1;
        while target_rank >= 0 {
            let mut target_file = file - 1;
            while target_file <= file + 1 {
                if target_file >= 0 && target_file < 8 {
                    masks[Color::Black as usize][square] |=
                        1_u64 << ((target_rank as u32) * 8 + target_file as u32);
                }
                target_file += 1;
            }
            target_rank -= 1;
        }

        square += 1;
    }
    masks
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

    use super::{evaluate, pawn_structure};

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
    fn passed_pawn_beats_same_pawn_blocked_by_enemy_pawn_structure() {
        let passed = Position::from_fen("7k/p7/8/3P4/8/8/8/7K w - - 0 1").expect("valid FEN");
        let blocked = Position::from_fen("7k/8/3p4/3P4/8/8/8/7K w - - 0 1").expect("valid FEN");
        let passed_score = pawn_structure(&passed, Color::White);
        let blocked_score = pawn_structure(&blocked, Color::White);
        assert!(passed_score.0 > blocked_score.0);
        assert!(passed_score.1 > blocked_score.1);
    }

    #[test]
    fn supported_pawns_score_better_than_isolated_pawns() {
        let connected = Position::from_fen("7k/8/8/8/3P4/2P5/7p/7K w - - 0 1")
            .expect("valid FEN");
        let isolated = Position::from_fen("7k/8/8/8/3P4/P7/7p/7K w - - 0 1")
            .expect("valid FEN");
        let connected_score = pawn_structure(&connected, Color::White);
        let isolated_score = pawn_structure(&isolated, Color::White);
        assert!(connected_score.0 > isolated_score.0);
        assert!(connected_score.1 > isolated_score.1);
    }
}
