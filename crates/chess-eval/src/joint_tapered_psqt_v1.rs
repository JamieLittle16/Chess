use chess_core::{Bitboard, Color, PieceKind, Position, Square};

const FEATURE_COUNT: usize = 19;
const DOUBLED_PAWNS: usize = 0;
const PAWN_ISLANDS: usize = 1;
const ISOLATED_PAWNS: usize = 2;
const SUPPORTED_PAWNS: usize = 3;
const PASSED_RANK_2: usize = 4;
const ROOK_SEVENTH: usize = 9;
const MINOR_OUTPOSTS: usize = 10;
const KING_SHIELD: usize = 11;
const KING_OPEN_FILES: usize = 12;
const PAWN_THREATS: usize = 13;
const CENTRAL_PAWN_CONTROL: usize = 14;
const CENTRAL_OCCUPANCY: usize = 15;
const BISHOP_PAIR: usize = 16;
const ROOK_OPEN_FILE: usize = 17;
const ROOK_SEMI_OPEN_FILE: usize = 18;

const FILE_A: u64 = 0x0101_0101_0101_0101;
const FILE_H: u64 = 0x8080_8080_8080_8080;
const CENTRAL_16: u64 = 0x0000_3c3c_3c3c_0000;
const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();

/// Ridge-fitted correction tables over the frozen 2,500-position Stockfish-19 teacher corpus.
///
/// Each piece uses a color-relative, file-mirrored 32-square table. The accepted geometric PSQT and
/// material evaluator remains the prior; these values are corrections only. The fit used alpha=100
/// and rounded each coefficient to the nearest centipawn-like integer after fitting.
const MG_PSQT: [i16; 192] = [
    0, 0, 0, 0, 5, 14, 25, -57, -19, 54, -36, -21, 4, 14, 2, 20, -14, 0, -27, -7, -1, -1, 10, -17,
    3, 14, -22, 6, 0, 0, 0, 0, -4, -12, 21, -31, 0, 2, -14, 2, -20, 10, 6, -1, -28, -7, 48, -15, 9,
    27, -6, 21, 8, 29, 6, 19, -5, 0, 10, -7, 0, 0, 9, 1, -7, -2, -22, -5, -4, 32, -12, -15, 5, -18,
    -3, 24, 4, 31, -33, -18, -2, 8, 15, -2, 10, 31, -23, -10, 16, -1, -2, -2, -1, 0, 2, 12, -19,
    17, 1, -6, -22, 2, 20, -5, -63, -4, 24, -19, 19, 1, -1, -15, -20, 13, 10, 4, 14, -4, 48, -3,
    21, -16, 3, 1, 10, -3, 2, -15, -14, 8, -13, -37, -17, 8, 1, -35, 8, 2, -9, -21, -12, 51, 4, 8,
    46, -18, 22, 1, -2, 1, -9, 6, -4, 8, 32, 17, -13, 12, 21, 21, -11, 22, -33, 46, -25, 14, 13, 2,
    -3, -24, -6, -10, -6, -7, 2, 2, -1, 1, 3, 5, -4, 5, 6, 4, 0, 3, 4, 1, -2, 0, 0, 0,
];

const EG_PSQT: [i16; 192] = [
    0, 0, 0, 0, -11, 39, 88, -5, -33, 44, -34, 16, 25, -4, 10, -52, 8, 26, 17, -82, 40, -10, 12,
    -30, 43, 90, 0, 20, 0, 0, 0, 0, -3, 7, 18, -22, -5, 7, -11, 8, -9, 2, -6, 0, -17, -2, 4, -5, 8,
    3, -5, 18, 2, -1, 8, 16, -1, 8, 6, -21, -1, 0, 6, -2, -15, -5, 6, 2, -5, -14, -32, 6, 11, -19,
    -17, -11, 4, 18, -10, -12, 5, 33, -13, 1, 14, 13, 8, -29, 6, 6, -3, 4, -1, -2, 6, 3, -30, 26,
    38, -10, -4, 2, -4, -10, -20, 6, -11, -4, 13, 34, 9, -16, 23, 6, -4, 2, 32, 12, 19, -3, 41, 10,
    11, 16, 33, 25, 17, -10, -14, 3, -7, -12, -4, 3, -13, -15, 7, -7, -18, -22, 4, 46, 16, 7, 23,
    9, 26, 33, -8, 0, 6, 31, 5, 28, 30, 52, 17, 35, 36, 45, -3, -5, -33, -40, -55, 12, 14, -14,
    -21, -26, 9, -4, -52, -8, 13, 3, -2, 6, 52, 29, -42, 33, 60, 27, 0, 9, 26, 31, -24, 3, -1, 0,
];

const MG_CHEAP: [i16; FEATURE_COUNT] = [
    -17, -29, 6, 6, 13, 3, -11, 45, 1, 9, 39, 27, -63, 28, 14, 7, 48, 36, -5,
];

const EG_CHEAP: [i16; FEATURE_COUNT] = [
    -20, 47, -19, 22, 11, -10, 49, 105, 154, 78, 8, 6, 94, 31, -18, 62, -7, 76, 34,
];

pub(crate) const TEMPO_CORRECTION: i32 = 64;

#[inline]
pub(crate) fn piece_square_correction(
    kind: PieceKind,
    color: Color,
    file: u8,
    rank: u8,
) -> (i32, i32) {
    let relative_rank = match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    };
    let mirrored_file = file.min(7 - file);
    let square_index = usize::from(relative_rank) * 4 + usize::from(mirrored_file);
    let index = kind.index() * 32 + square_index;
    (i32::from(MG_PSQT[index]), i32::from(EG_PSQT[index]))
}

pub(crate) fn structure_correction(position: &Position, color: Color) -> (i32, i32) {
    let values = cheap_features(position, color);
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    for index in 0..FEATURE_COUNT {
        middle_game += values[index] * i32::from(MG_CHEAP[index]);
        end_game += values[index] * i32::from(EG_CHEAP[index]);
    }
    (middle_game, end_game)
}

fn cheap_features(position: &Position, color: Color) -> [i32; FEATURE_COUNT] {
    let mut values = [0_i32; FEATURE_COUNT];
    let pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let own_pawn_attacks = pawn_attack_union(position, color);
    let enemy_pawn_attacks = pawn_attack_union(position, color.opposite());
    let mut file_counts = [0_u8; 8];

    for square in pawns {
        file_counts[usize::from(square.file())] += 1;
    }

    values[DOUBLED_PAWNS] = file_counts
        .iter()
        .map(|&count| i32::from(count.saturating_sub(1)))
        .sum();
    values[PAWN_ISLANDS] = (0..8)
        .filter(|&file| file_counts[file] != 0 && (file == 0 || file_counts[file - 1] == 0))
        .count() as i32;

    for square in pawns {
        let file = usize::from(square.file());
        if (file == 0 || file_counts[file - 1] == 0) && (file == 7 || file_counts[file + 1] == 0) {
            values[ISOLATED_PAWNS] += 1;
        }
        if own_pawn_attacks.contains(square) {
            values[SUPPORTED_PAWNS] += 1;
        }
        if is_passed_pawn(square, color, enemy_pawns) {
            let relative_rank = relative_rank(color, square.rank());
            if (2..=6).contains(&relative_rank) {
                values[PASSED_RANK_2 + usize::from(relative_rank - 2)] += 1;
            }
        }
    }

    for square in position.pieces(color, PieceKind::Rook) {
        if relative_rank(color, square.rank()) == 6 {
            values[ROOK_SEVENTH] += 1;
        }
    }

    for kind in [PieceKind::Knight, PieceKind::Bishop] {
        for square in position.pieces(color, kind) {
            let rank = relative_rank(color, square.rank());
            if (3..=5).contains(&rank)
                && own_pawn_attacks.contains(square)
                && !enemy_pawn_attacks.contains(square)
            {
                values[MINOR_OUTPOSTS] += 1;
            }
        }
    }

    if let Some(king) = position.king_square(color) {
        let king_file = i32::from(king.file());
        let king_rank = i32::from(king.rank());
        let forward = if color == Color::White { 1 } else { -1 };
        for file_delta in -1..=1 {
            let file = king_file + file_delta;
            if !(0..8).contains(&file) {
                continue;
            }
            if file_counts[file as usize] == 0 {
                values[KING_OPEN_FILES] += 1;
            }
            for step in 1..=2 {
                let rank = king_rank + forward * step;
                if !(0..8).contains(&rank) {
                    continue;
                }
                let bit = 1_u64 << (rank * 8 + file);
                if pawns.raw() & bit != 0 {
                    values[KING_SHIELD] += if step == 1 { 2 } else { 1 };
                }
            }
        }
    }

    values[PAWN_THREATS] = (own_pawn_attacks & position.pieces(color.opposite(), PieceKind::Knight))
        .count() as i32
        * 3
        + (own_pawn_attacks & position.pieces(color.opposite(), PieceKind::Bishop)).count() as i32
            * 3
        + (own_pawn_attacks & position.pieces(color.opposite(), PieceKind::Rook)).count() as i32
            * 5
        + (own_pawn_attacks & position.pieces(color.opposite(), PieceKind::Queen)).count() as i32
            * 9;
    values[CENTRAL_PAWN_CONTROL] = (own_pawn_attacks.raw() & CENTRAL_16).count_ones() as i32;
    values[CENTRAL_OCCUPANCY] = (position.occupancy(color).raw() & CENTRAL_16).count_ones() as i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {
        values[BISHOP_PAIR] = 1;
    }

    let own_pawns_raw = pawns.raw();
    let enemy_pawns_raw = enemy_pawns.raw();
    for rook in position.pieces(color, PieceKind::Rook) {
        let file_mask = FILE_A << u32::from(rook.file());
        if own_pawns_raw & file_mask != 0 {
            continue;
        }
        if enemy_pawns_raw & file_mask == 0 {
            values[ROOK_OPEN_FILE] += 1;
        } else {
            values[ROOK_SEMI_OPEN_FILE] += 1;
        }
    }

    values
}

#[inline]
fn pawn_attack_union(position: &Position, color: Color) -> Bitboard {
    let pawns = position.pieces(color, PieceKind::Pawn).raw();
    let attacks = match color {
        Color::White => ((pawns & !FILE_A) << 7) | ((pawns & !FILE_H) << 9),
        Color::Black => ((pawns & !FILE_H) >> 7) | ((pawns & !FILE_A) >> 9),
    };
    Bitboard::from_raw(attacks)
}

#[inline]
fn is_passed_pawn(square: Square, color: Color, enemy_pawns: Bitboard) -> bool {
    enemy_pawns.raw() & PASSED_PAWN_MASKS[color.index()][usize::from(square.index())] == 0
}

const fn generate_passed_pawn_masks() -> [[u64; 64]; 2] {
    let mut masks = [[0_u64; 64]; 2];
    let mut square = 0_usize;
    while square < 64 {
        let file = (square & 7) as i32;
        let rank = (square >> 3) as i32;
        let mut target_file = file - 1;
        while target_file <= file + 1 {
            if target_file >= 0 && target_file < 8 {
                let mut white_rank = rank + 1;
                while white_rank < 8 {
                    masks[Color::White as usize][square] |=
                        1_u64 << ((white_rank * 8 + target_file) as u32);
                    white_rank += 1;
                }
                let mut black_rank = rank - 1;
                while black_rank >= 0 {
                    masks[Color::Black as usize][square] |=
                        1_u64 << ((black_rank * 8 + target_file) as u32);
                    black_rank -= 1;
                }
            }
            target_file += 1;
        }
        square += 1;
    }
    masks
}

#[inline]
const fn relative_rank(color: Color, rank: u8) -> u8 {
    match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, PieceKind, Position};

    use super::{piece_square_correction, structure_correction};

    #[test]
    fn piece_square_correction_is_file_symmetric() {
        for color in Color::ALL {
            for kind in PieceKind::ALL {
                for rank in 0..8 {
                    for file in 0..4 {
                        assert_eq!(
                            piece_square_correction(kind, color, file, rank),
                            piece_square_correction(kind, color, 7 - file, rank)
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn structure_correction_is_finite_on_kiwipete() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        for color in Color::ALL {
            let (mg, eg) = structure_correction(&position, color);
            assert!(mg.abs() < 2_000);
            assert!(eg.abs() < 2_000);
        }
    }
}
