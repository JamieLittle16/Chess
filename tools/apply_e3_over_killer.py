#!/usr/bin/env python3
"""Apply the accepted-isolation E3 pawn evaluator over the killer production baseline."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-eval/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    "use chess_core::{Color, PieceKind, Position};",
    "use chess_core::{Bitboard, Color, PieceKind, Position, Square, pawn_attacks};",
    "imports",
)
text = replace_once(
    text,
    "const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);\n",
    "const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);\n\n"
    "const FILE_MASKS: [u64; 8] = generate_file_masks();\n"
    "const ADJACENT_FILE_MASKS: [u64; 8] = generate_adjacent_file_masks();\n"
    "const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();\n\n"
    "const DOUBLED_PAWN_MG_PENALTY: i32 = 10;\n"
    "const DOUBLED_PAWN_EG_PENALTY: i32 = 15;\n"
    "const ISOLATED_PAWN_MG_PENALTY: i32 = 12;\n"
    "const ISOLATED_PAWN_EG_PENALTY: i32 = 10;\n"
    "const SUPPORTED_PAWN_MG_BONUS: i32 = 6;\n"
    "const SUPPORTED_PAWN_EG_BONUS: i32 = 10;\n"
    "const PHALANX_PAWN_MG_BONUS: i32 = 4;\n"
    "const PHALANX_PAWN_EG_BONUS: i32 = 6;\n"
    "const PASSED_PAWN_MG_BONUS: [i32; 8] = [0, 0, 0, 5, 12, 25, 45, 0];\n"
    "const PASSED_PAWN_EG_BONUS: [i32; 8] = [0, 0, 0, 10, 25, 50, 90, 0];\n",
    "constants",
)
text = replace_once(
    text,
    "    for color in Color::ALL {\n        let sign = if color == Color::White { 1 } else { -1 };\n        for kind in PieceKind::ALL {",
    "    for color in Color::ALL {\n        let sign = if color == Color::White { 1 } else { -1 };\n"
    "        let (pawn_middle_game, pawn_end_game) = pawn_structure(position, color);\n"
    "        middle_game += sign * pawn_middle_game;\n"
    "        end_game += sign * pawn_end_game;\n\n"
    "        for kind in PieceKind::ALL {",
    "evaluation accumulation",
)

old_relative = '''#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {
    let relative_rank = match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    };
    (relative_rank as usize) * 8 + file as usize
}
'''
new_helpers = '''fn pawn_structure(position: &Position, color: Color) -> (i32, i32) {
    let pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

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
'''
text = replace_once(text, old_relative, new_helpers, "helpers")
text = replace_once(
    text,
    "    use chess_core::Position;\n\n    use super::evaluate;",
    "    use chess_core::{Color, Position};\n\n    use super::{evaluate, pawn_structure};",
    "test imports",
)
text = replace_once(
    text,
    "    #[test]\n    fn endgame_king_is_rewarded_for_centralisation() {",
    '''    #[test]
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
        let supported = Position::from_fen("7k/8/8/8/3P4/2P5/8/7K w - - 0 1").expect("valid FEN");
        let isolated = Position::from_fen("7k/8/8/8/3P4/8/P7/7K w - - 0 1").expect("valid FEN");
        assert!(pawn_structure(&supported, Color::White).0 > pawn_structure(&isolated, Color::White).0);
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "pawn tests",
)
path.write_text(text)
