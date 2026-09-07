#!/usr/bin/env python3
"""Apply rook/passed-pawn conversion relationships over accepted LMR production."""
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
    "use chess_core::{Color, PieceKind, Position, rook_attacks};",
    "rook passer imports",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();
const OWN_ROOK_BEHIND_PASSER_MG: [i32; 8] = [0, 0, 0, 2, 4, 7, 10, 0];
const OWN_ROOK_BEHIND_PASSER_EG: [i32; 8] = [0, 0, 0, 7, 13, 22, 34, 0];
const ENEMY_ROOK_BEHIND_PASSER_MG: [i32; 8] = [0, 0, 0, 3, 5, 8, 12, 0];
const ENEMY_ROOK_BEHIND_PASSER_EG: [i32; 8] = [0, 0, 0, 9, 16, 26, 38, 0];
const BLOCKADED_PASSER_MG: [i32; 8] = [0, 0, 0, 2, 4, 7, 12, 0];
const BLOCKADED_PASSER_EG: [i32; 8] = [0, 0, 0, 5, 10, 18, 30, 0];''',
    "rook passer constants",
)

text = replace_once(
    text,
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    '''    let (mut middle_game, mut end_game) = rook_passer_coordination(position, color);

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    "rook passer integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn rook_passer_coordination(position: &Position, color: Color) -> (i32, i32) {
    let enemy = color.opposite();
    let enemy_pawns = position.pieces(enemy, PieceKind::Pawn).raw();
    let own_rooks = position.pieces(color, PieceKind::Rook);
    let enemy_rooks = position.pieces(enemy, PieceKind::Rook);
    let occupied = position.occupied();
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    for pawn in position.pieces(color, PieceKind::Pawn) {
        let mask = PASSED_PAWN_MASKS[color.index()][usize::from(pawn.index())];
        if enemy_pawns & mask != 0 {
            continue;
        }
        let relative_rank = match color {
            Color::White => usize::from(pawn.rank()),
            Color::Black => usize::from(7 - pawn.rank()),
        };
        if relative_rank < 3 || relative_rank >= 7 {
            continue;
        }

        for rook in own_rooks {
            if rook.file() == pawn.file()
                && is_behind_pawn(color, rook.rank(), pawn.rank())
                && rook_attacks(rook, occupied).contains(pawn)
            {
                middle_game += OWN_ROOK_BEHIND_PASSER_MG[relative_rank];
                end_game += OWN_ROOK_BEHIND_PASSER_EG[relative_rank];
                break;
            }
        }
        for rook in enemy_rooks {
            if rook.file() == pawn.file()
                && is_behind_pawn(color, rook.rank(), pawn.rank())
                && rook_attacks(rook, occupied).contains(pawn)
            {
                middle_game -= ENEMY_ROOK_BEHIND_PASSER_MG[relative_rank];
                end_game -= ENEMY_ROOK_BEHIND_PASSER_EG[relative_rank];
                break;
            }
        }

        if let Some(front) = pawn_forward_one(pawn, color)
            && position
                .piece_at(front)
                .is_some_and(|piece| piece.color() == enemy)
        {
            middle_game -= BLOCKADED_PASSER_MG[relative_rank];
            end_game -= BLOCKADED_PASSER_EG[relative_rank];
        }
    }

    (middle_game, end_game)
}

#[inline]
fn is_behind_pawn(color: Color, rook_rank: u8, pawn_rank: u8) -> bool {
    match color {
        Color::White => rook_rank < pawn_rank,
        Color::Black => rook_rank > pawn_rank,
    }
}

#[inline]
fn pawn_forward_one(pawn: chess_core::Square, color: Color) -> Option<chess_core::Square> {
    let rank = match color {
        Color::White => pawn.rank().checked_add(1)?,
        Color::Black => pawn.rank().checked_sub(1)?,
    };
    chess_core::Square::from_file_rank(pawn.file(), rank)
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "rook passer helper",
)

text = replace_once(
    text,
    '''#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {''',
    '''const fn generate_passed_pawn_masks() -> [[u64; 64]; 2] {
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

#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {''',
    "passed mask generator",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{evaluate, piece_structure, rook_passer_coordination};",
    "rook passer test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn rook_actually_connected_behind_own_passer_is_rewarded() {
        let behind =
            Position::from_fen("7k/8/8/4P3/8/8/8/4R2K w - - 0 1").expect("valid FEN");
        let aside =
            Position::from_fen("7k/8/8/4P3/8/8/8/R6K w - - 0 1").expect("valid FEN");
        assert!(
            rook_passer_coordination(&behind, Color::White).1
                > rook_passer_coordination(&aside, Color::White).1
        );
    }

    #[test]
    fn enemy_rook_restraining_passer_from_behind_is_a_real_conversion_cost() {
        let restrained =
            Position::from_fen("7k/8/8/4P3/8/8/8/4r2K w - - 0 1").expect("valid FEN");
        let aside =
            Position::from_fen("7k/8/8/4P3/8/8/8/r6K w - - 0 1").expect("valid FEN");
        assert!(
            rook_passer_coordination(&restrained, Color::White).1
                < rook_passer_coordination(&aside, Color::White).1
        );
    }

    #[test]
    fn concrete_blockader_reduces_advanced_passer_convertibility() {
        let blocked =
            Position::from_fen("7k/8/4n3/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");
        let clear =
            Position::from_fen("7k/8/n7/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");
        assert!(
            rook_passer_coordination(&blocked, Color::White).1
                < rook_passer_coordination(&clear, Color::White).1
        );
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "rook passer tests",
)

path.write_text(text)
