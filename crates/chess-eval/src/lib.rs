//! Transparent classical evaluation used as the permanent reference baseline.
//!
//! M4 E1 extends the original material-only control with a deliberately small tapered piece-square
//! model. The tables are generated at compile time from transparent geometric rules rather than
//! copied from another engine. Runtime evaluation remains allocation-free: iterate the existing
//! piece bitboards, perform table lookups, and interpolate one middle-game/end-game score pair.

pub mod nnue;
#[cfg(feature = "search-trace")]
mod search_trace;

use chess_core::{Color, PieceKind, Position};

/// Conventional centipawn-like material values retained from the material-only reference.
pub const PIECE_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

const PHASE_WEIGHTS: [i32; 6] = [0, 1, 1, 2, 4, 0];
const MAX_PHASE: i32 = 24;
const MG_PSQT: [[i16; 64]; 6] = generate_psqt(false);
const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);

const BISHOP_PAIR_MG_BONUS: i32 = 30;
const BISHOP_PAIR_EG_BONUS: i32 = 45;
const ROOK_OPEN_FILE_MG_BONUS: i32 = 16;
const ROOK_OPEN_FILE_EG_BONUS: i32 = 12;
const ROOK_SEMI_OPEN_FILE_MG_BONUS: i32 = 8;
const ROOK_SEMI_OPEN_FILE_EG_BONUS: i32 = 6;
const FILE_A: u64 = 0x0101_0101_0101_0101;

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
/// score interpolates between middle-game and end-game piece-square preferences using remaining
/// non-pawn material. Black reuses the same tables by vertically mirroring each square.
#[must_use]
pub fn evaluate(position: &Position) -> i32 {
    #[cfg(feature = "search-trace")]
    search_trace::observe(position);

    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let mut phase = 0_i32;

    for color in Color::ALL {
        let sign = if color == Color::White { 1 } else { -1 };
        let (structure_middle_game, structure_end_game) = piece_structure(position, color);
        middle_game += sign * structure_middle_game;
        end_game += sign * structure_end_game;

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

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {
        middle_game += BISHOP_PAIR_MG_BONUS;
        end_game += BISHOP_PAIR_EG_BONUS;
    }

    let own_pawns = position.pieces(color, PieceKind::Pawn).raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn).raw();
    for rook in position.pieces(color, PieceKind::Rook) {
        let file_mask = FILE_A << u32::from(rook.file());
        if own_pawns & file_mask != 0 {
            continue;
        }
        if enemy_pawns & file_mask == 0 {
            middle_game += ROOK_OPEN_FILE_MG_BONUS;
            end_game += ROOK_OPEN_FILE_EG_BONUS;
        } else {
            middle_game += ROOK_SEMI_OPEN_FILE_MG_BONUS;
            end_game += ROOK_SEMI_OPEN_FILE_EG_BONUS;
        }
    }

    (middle_game, end_game)
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
        // Pawns gain more from safe advancement in the endgame. A tiny central-file bonus nudges
        // healthy central occupation without attempting to model pawn structure yet.
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
        // Knights are the strongest centralisation signal in v1.
        1 => {
            if end_game {
                centre * 3 - 18
            } else {
                centre * 4 - 24
            }
        }
        // Bishops prefer activity but are less sensitive to central squares than knights.
        2 => {
            if end_game {
                centre * 2 - 6
            } else {
                centre * 2 - 8
            }
        }
        // Rooks get a modest seventh-rank/activity signal. File structure is deliberately deferred
        // to a separate experiment so E1 remains a pure placement baseline.
        3 => {
            let seventh = if rank == 6 { 14 } else { 0 };
            if end_game {
                seventh + rank * 2
            } else {
                seventh + rank
            }
        }
        // Queen placement is intentionally weakly weighted to avoid paying for brittle opening
        // assumptions before development/king-safety terms exist.
        4 => {
            if end_game {
                centre * 2 - 8
            } else {
                centre - 8
            }
        }
        // Middle-game kings prefer the home rank and castled files. End-game kings reverse that
        // preference and are rewarded for centralisation.
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

    use super::{evaluate, piece_structure};

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
    fn bishop_pair_and_rook_file_terms_are_detected_directly() {
        let bishops = Position::from_fen("7k/8/8/8/8/8/8/2B2B1K w - - 0 1").expect("valid FEN");
        assert_eq!(piece_structure(&bishops, Color::White), (30, 45));

        let open_rook = Position::from_fen("7k/8/8/8/8/8/8/R6K w - - 0 1").expect("valid FEN");
        assert_eq!(piece_structure(&open_rook, Color::White), (16, 12));

        let semi_open = Position::from_fen("7k/p7/8/8/8/8/8/R6K w - - 0 1").expect("valid FEN");
        assert_eq!(piece_structure(&semi_open, Color::White), (8, 6));

        let closed = Position::from_fen("7k/8/8/8/8/8/P7/R6K w - - 0 1").expect("valid FEN");
        assert_eq!(piece_structure(&closed, Color::White), (0, 0));
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {
        let central = Position::from_fen("7k/8/8/8/3K4/8/8/8 w - - 0 1").expect("valid FEN");
        let corner = Position::from_fen("7k/8/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        assert!(evaluate(&central) > evaluate(&corner));
    }
}
