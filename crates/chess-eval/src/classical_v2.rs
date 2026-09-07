use chess_core::{
    Bitboard, Color, PieceKind, Position, bishop_attacks, king_attacks, knight_attacks,
    pawn_attacks, queen_attacks, rook_attacks,
};

use super::{MAX_PHASE, PHASE_WEIGHTS};

const FEATURE_COUNT: usize = 21;
const DOUBLED_PAWNS: usize = 0;
const PAWN_ISLANDS: usize = 1;
const ISOLATED_PAWNS: usize = 2;
const SUPPORTED_PAWNS: usize = 3;
const PASSED_RANK_2: usize = 4;
const PASSED_RANK_3: usize = 5;
const PASSED_RANK_4: usize = 6;
const PASSED_RANK_5: usize = 7;
const PASSED_RANK_6: usize = 8;
const SAFE_MOBILITY_KNIGHT: usize = 9;
const SAFE_MOBILITY_BISHOP: usize = 10;
const SAFE_MOBILITY_ROOK: usize = 11;
const SAFE_MOBILITY_QUEEN: usize = 12;
const ROOK_SEVENTH: usize = 13;
const MINOR_OUTPOSTS: usize = 14;
const KING_SHIELD: usize = 15;
const KING_OPEN_FILES: usize = 16;
const KING_RING_PRESSURE: usize = 17;
const PAWN_THREATS: usize = 18;
const CENTRAL_PAWN_CONTROL: usize = 19;
const CENTRAL_OCCUPANCY: usize = 20;

const CENTRAL_16: u64 = 0x0000_3c3c_3c3c_0000;

/// Two frozen fits over the same small structural feature set.
///
/// These are deliberately experimental. `CpResidual` was ridge-fitted to clipped Stockfish
/// centipawn residuals. `WdlResidual` was fitted to a logit transform of the Stockfish WDL
/// expectation, which is the more search-aligned target. Neither table is production-qualified;
/// equal-time games decide whether either survives.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(crate) enum JointClassicalVariant {
    CpResidual,
    WdlResidual,
}

impl JointClassicalVariant {
    pub(crate) fn from_env(value: &str) -> Option<Self> {
        match value {
            "cp" => Some(Self::CpResidual),
            "wdl" => Some(Self::WdlResidual),
            _ => None,
        }
    }

    const fn middle_game_weights(self) -> &'static [i16; FEATURE_COUNT] {
        match self {
            Self::CpResidual => &[
                -18, -15, -3, -4, 41, 29, -12, 133, -38, 12, 7, 8, 1, 10, 34, 21, -45, -33, 18, 10,
                -6,
            ],
            Self::WdlResidual => &[
                -19, -37, -27, -10, 108, -2, 2, 159, 57, 11, 9, 13, -7, 51, 26, 24, -50, -29, 20,
                30, -2,
            ],
        }
    }

    const fn end_game_weights(self) -> &'static [i16; FEATURE_COUNT] {
        match self {
            Self::CpResidual => &[
                -39, 10, -11, 27, 4, -9, 49, 134, 273, 2, 1, 10, 13, 74, 24, 4, 63, -12, 37, -6, 20,
            ],
            Self::WdlResidual => &[
                -72, -26, -22, 18, -16, 14, 24, 67, 157, -6, -7, 2, -18, 23, 15, -4, 24, 15, 37,
                13, -13,
            ],
        }
    }

    const fn tempo(self) -> i32 {
        match self {
            Self::CpResidual => 77,
            Self::WdlResidual => 71,
        }
    }
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct SideFeatures {
    values: [i32; FEATURE_COUNT],
    attacks: Bitboard,
}

/// Return the frozen v2 correction from the side-to-move perspective.
///
/// The accepted evaluator remains the prior. This function contributes only a compact tapered
/// residual. Runtime work is allocation-free and uses the same precomputed attack primitives as
/// move generation; no legal-move list is constructed.
pub(crate) fn residual(position: &Position, variant: JointClassicalVariant) -> i32 {
    let occupied = position.occupied();
    let own_occupied = [
        occupied_by(position, Color::White),
        occupied_by(position, Color::Black),
    ];
    let pawn_attack_maps = [
        pawn_attack_union(position, Color::White),
        pawn_attack_union(position, Color::Black),
    ];

    let mut white = analyze_side(
        position,
        Color::White,
        occupied,
        own_occupied[Color::White.index()],
        pawn_attack_maps[Color::White.index()],
        pawn_attack_maps[Color::Black.index()],
    );
    let mut black = analyze_side(
        position,
        Color::Black,
        occupied,
        own_occupied[Color::Black.index()],
        pawn_attack_maps[Color::Black.index()],
        pawn_attack_maps[Color::White.index()],
    );

    white.values[KING_RING_PRESSURE] = king_ring_pressure(position, Color::White, black.attacks);
    black.values[KING_RING_PRESSURE] = king_ring_pressure(position, Color::Black, white.attacks);

    let mg_weights = variant.middle_game_weights();
    let eg_weights = variant.end_game_weights();
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    for index in 0..FEATURE_COUNT {
        let difference = white.values[index] - black.values[index];
        middle_game = middle_game.saturating_add(difference * i32::from(mg_weights[index]));
        end_game = end_game.saturating_add(difference * i32::from(eg_weights[index]));
    }

    let phase = phase(position);
    let white_minus_black = (middle_game * phase + end_game * (MAX_PHASE - phase)) / MAX_PHASE;
    let oriented = match position.side_to_move() {
        Color::White => white_minus_black,
        Color::Black => -white_minus_black,
    };
    oriented.saturating_add(variant.tempo())
}

fn analyze_side(
    position: &Position,
    color: Color,
    occupied: Bitboard,
    own_occupied: Bitboard,
    own_pawn_attacks: Bitboard,
    enemy_pawn_attacks: Bitboard,
) -> SideFeatures {
    let mut result = SideFeatures::default();
    let pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let mut file_counts = [0_u8; 8];
    for square in pawns {
        file_counts[usize::from(square.file())] += 1;
    }

    result.values[DOUBLED_PAWNS] = file_counts
        .iter()
        .map(|&count| i32::from(count.saturating_sub(1)))
        .sum();
    result.values[PAWN_ISLANDS] = (0..8)
        .filter(|&file| file_counts[file] != 0 && (file == 0 || file_counts[file - 1] == 0))
        .count() as i32;

    for square in pawns {
        let file = usize::from(square.file());
        let isolated =
            (file == 0 || file_counts[file - 1] == 0) && (file == 7 || file_counts[file + 1] == 0);
        if isolated {
            result.values[ISOLATED_PAWNS] += 1;
        }
        if own_pawn_attacks.contains(square) {
            result.values[SUPPORTED_PAWNS] += 1;
        }
        if is_passed_pawn(square.file(), square.rank(), color, enemy_pawns) {
            let relative_rank = relative_rank(color, square.rank());
            if (2..=6).contains(&relative_rank) {
                result.values[PASSED_RANK_2 + usize::from(relative_rank - 2)] += 1;
            }
        }
    }

    let enemy_pawn_raw = enemy_pawn_attacks.raw();
    for (kind, feature) in [
        (PieceKind::Knight, SAFE_MOBILITY_KNIGHT),
        (PieceKind::Bishop, SAFE_MOBILITY_BISHOP),
        (PieceKind::Rook, SAFE_MOBILITY_ROOK),
        (PieceKind::Queen, SAFE_MOBILITY_QUEEN),
    ] {
        for square in position.pieces(color, kind) {
            let attacks = match kind {
                PieceKind::Knight => knight_attacks(square),
                PieceKind::Bishop => bishop_attacks(square, occupied),
                PieceKind::Rook => rook_attacks(square, occupied),
                PieceKind::Queen => queen_attacks(square, occupied),
                PieceKind::Pawn | PieceKind::King => Bitboard::EMPTY,
            };
            result.attacks = result.attacks | attacks;
            let safe = attacks.raw() & !own_occupied.raw() & !enemy_pawn_raw;
            result.values[feature] += safe.count_ones() as i32;
        }
    }

    // Add leaper/pawn/king attacks to the union used only for king-ring pressure. Slider attacks
    // were already accumulated while computing mobility, so no duplicate slider work is paid.
    result.attacks = result.attacks | own_pawn_attacks;
    for square in position.pieces(color, PieceKind::Knight) {
        result.attacks = result.attacks | knight_attacks(square);
    }
    if let Some(king) = position.king_square(color) {
        result.attacks = result.attacks | king_attacks(king);
    }

    for square in position.pieces(color, PieceKind::Rook) {
        if relative_rank(color, square.rank()) == 6 {
            result.values[ROOK_SEVENTH] += 1;
        }
    }

    for kind in [PieceKind::Knight, PieceKind::Bishop] {
        for square in position.pieces(color, kind) {
            let rank = relative_rank(color, square.rank());
            if (3..=5).contains(&rank)
                && own_pawn_attacks.contains(square)
                && !enemy_pawn_attacks.contains(square)
            {
                result.values[MINOR_OUTPOSTS] += 1;
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
                result.values[KING_OPEN_FILES] += 1;
            }
            for step in 1..=2 {
                let rank = king_rank + forward * step;
                if !(0..8).contains(&rank) {
                    continue;
                }
                let bit = 1_u64 << (rank * 8 + file);
                if pawns.raw() & bit != 0 {
                    result.values[KING_SHIELD] += if step == 1 { 2 } else { 1 };
                }
            }
        }
    }

    let enemy_non_pawns = [
        (PieceKind::Knight, 3_i32),
        (PieceKind::Bishop, 3),
        (PieceKind::Rook, 5),
        (PieceKind::Queen, 9),
    ];
    for (kind, weight) in enemy_non_pawns {
        result.values[PAWN_THREATS] +=
            (own_pawn_attacks & position.pieces(color.opposite(), kind)).count() as i32 * weight;
    }

    result.values[CENTRAL_PAWN_CONTROL] = (own_pawn_attacks.raw() & CENTRAL_16).count_ones() as i32;
    result.values[CENTRAL_OCCUPANCY] = (own_occupied.raw() & CENTRAL_16).count_ones() as i32;

    result
}

#[inline]
fn occupied_by(position: &Position, color: Color) -> Bitboard {
    let mut occupied = Bitboard::EMPTY;
    for kind in PieceKind::ALL {
        occupied = occupied | position.pieces(color, kind);
    }
    occupied
}

#[inline]
fn pawn_attack_union(position: &Position, color: Color) -> Bitboard {
    let mut attacks = Bitboard::EMPTY;
    for square in position.pieces(color, PieceKind::Pawn) {
        attacks = attacks | pawn_attacks(color, square);
    }
    attacks
}

fn is_passed_pawn(file: u8, rank: u8, color: Color, enemy_pawns: Bitboard) -> bool {
    for enemy in enemy_pawns {
        let enemy_file = enemy.file();
        if enemy_file.abs_diff(file) > 1 {
            continue;
        }
        let ahead = match color {
            Color::White => enemy.rank() > rank,
            Color::Black => enemy.rank() < rank,
        };
        if ahead {
            return false;
        }
    }
    true
}

#[inline]
const fn relative_rank(color: Color, rank: u8) -> u8 {
    match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    }
}

fn king_ring_pressure(position: &Position, color: Color, enemy_attacks: Bitboard) -> i32 {
    position.king_square(color).map_or(0, |king| {
        let ring = king_attacks(king).with(king);
        (ring & enemy_attacks).count() as i32
    })
}

fn phase(position: &Position) -> i32 {
    let mut phase = 0_i32;
    for color in Color::ALL {
        for kind in PieceKind::ALL {
            phase += position.pieces(color, kind).count() as i32 * PHASE_WEIGHTS[kind.index()];
        }
    }
    phase.min(MAX_PHASE)
}

#[cfg(test)]
mod tests {
    use chess_core::Position;

    use super::{JointClassicalVariant, residual};

    #[test]
    fn start_position_only_receives_the_fitted_tempo() {
        let position = Position::startpos();
        assert_eq!(residual(&position, JointClassicalVariant::CpResidual), 77);
        assert_eq!(residual(&position, JointClassicalVariant::WdlResidual), 71);
    }

    #[test]
    fn structural_residual_changes_on_a_damaged_pawn_structure() {
        let healthy = Position::from_fen("4k3/8/8/8/8/8/PP6/4K3 w - - 0 1").expect("valid FEN");
        let doubled = Position::from_fen("4k3/8/8/8/8/P7/P7/4K3 w - - 0 1").expect("valid FEN");
        assert_ne!(
            residual(&healthy, JointClassicalVariant::WdlResidual),
            residual(&doubled, JointClassicalVariant::WdlResidual)
        );
    }

    #[test]
    fn residual_is_bounded_on_kiwipete() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        for variant in [
            JointClassicalVariant::CpResidual,
            JointClassicalVariant::WdlResidual,
        ] {
            assert!(residual(&position, variant).abs() < 2_000);
        }
    }
}
