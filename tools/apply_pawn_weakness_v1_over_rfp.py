#!/usr/bin/env python3
"""Apply focused pawn-island and backward-pawn evaluation over accepted RFP."""
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
    "use chess_core::{Color, PieceKind, Position, Square, pawn_attacks};",
    "pawn-weakness imports",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const EXTRA_PAWN_ISLAND_MG_PENALTY: i32 = 5;
const EXTRA_PAWN_ISLAND_EG_PENALTY: i32 = 8;
const BACKWARD_PAWN_MG_PENALTY: i32 = 10;
const BACKWARD_PAWN_EG_PENALTY: i32 = 8;''',
    "pawn-weakness constants",
)

text = replace_once(
    text,
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let (pawn_middle_game, pawn_end_game) = pawn_weakness(position, color);
    middle_game += pawn_middle_game;
    end_game += pawn_end_game;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    "piece-structure integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn pawn_weakness(position: &Position, color: Color) -> (i32, i32) {
    let pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    // Count contiguous occupied pawn files as islands. This is cheaper and less brittle than
    // applying an isolated-pawn penalty independently to every pawn in a weak file cluster.
    let mut occupied_files = 0_u8;
    for pawn in pawns {
        occupied_files |= 1_u8 << pawn.file();
    }
    let island_starts = occupied_files & !occupied_files.wrapping_shl(1);
    let extra_islands = island_starts.count_ones().saturating_sub(1) as i32;
    middle_game -= extra_islands * EXTRA_PAWN_ISLAND_MG_PENALTY;
    end_game -= extra_islands * EXTRA_PAWN_ISLAND_EG_PENALTY;

    for pawn in position.pieces(color, PieceKind::Pawn) {
        if is_backward_pawn(position, color, pawn, pawns, enemy_pawns) {
            middle_game -= BACKWARD_PAWN_MG_PENALTY;
            end_game -= BACKWARD_PAWN_EG_PENALTY;
        }
    }

    (middle_game, end_game)
}

fn is_backward_pawn(
    position: &Position,
    color: Color,
    pawn: Square,
    own_pawns: chess_core::Bitboard,
    enemy_pawns: chess_core::Bitboard,
) -> bool {
    let Some(forward) = pawn_forward_square(pawn, color) else {
        return false;
    };
    if position.piece_at(forward).is_some() {
        return false;
    }

    // Enemy pawns that attack the square in front of our pawn lie on the reverse attack mask.
    if (pawn_attacks(color, forward) & enemy_pawns).is_empty() {
        return false;
    }

    // If another own pawn already attacks the advance square, advancing is structurally supported
    // and the pawn is not backward for this compact model.
    if !(pawn_attacks(color.opposite(), forward) & own_pawns).is_empty() {
        return false;
    }

    let pawn_rank = relative_rank(color, pawn.rank());
    for neighbour in own_pawns {
        if neighbour.file().abs_diff(pawn.file()) == 1
            && relative_rank(color, neighbour.rank()) > pawn_rank
        {
            return true;
        }
    }
    false
}

fn pawn_forward_square(pawn: Square, color: Color) -> Option<Square> {
    let rank = match color {
        Color::White => pawn.rank().checked_add(1)?,
        Color::Black => pawn.rank().checked_sub(1)?,
    };
    if rank >= 8 {
        return None;
    }
    Square::from_file_rank(pawn.file(), rank)
}

#[inline]
const fn relative_rank(color: Color, rank: u8) -> usize {
    match color {
        Color::White => rank as usize,
        Color::Black => (7 - rank) as usize,
    }
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "pawn-weakness helpers",
)

text = replace_once(
    text,
    '''#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {
    let relative_rank = match color {
        Color::White => rank,
        Color::Black => 7 - rank,
    };
    (relative_rank as usize) * 8 + file as usize
}''',
    '''#[inline]
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {
    relative_rank(color, rank) * 8 + file as usize
}''',
    "shared relative rank",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{evaluate, pawn_weakness, piece_structure};",
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn extra_pawn_island_is_a_structural_weakness() {
        let one_island =
            Position::from_fen("7k/8/8/8/8/8/PPPP4/7K w - - 0 1").expect("valid FEN");
        let two_islands =
            Position::from_fen("7k/8/8/8/8/8/PP2PP2/7K w - - 0 1").expect("valid FEN");
        assert!(
            pawn_weakness(&one_island, Color::White).1
                > pawn_weakness(&two_islands, Color::White).1
        );
    }

    #[test]
    fn pawn_blocked_by_enemy_pawn_control_behind_advanced_neighbour_is_backward() {
        let backward =
            Position::from_fen("7k/8/8/1p6/3P4/2P5/8/7K w - - 0 1").expect("valid FEN");
        let safe =
            Position::from_fen("7k/8/1p6/8/3P4/2P5/8/7K w - - 0 1").expect("valid FEN");
        assert!(
            pawn_weakness(&safe, Color::White).0
                > pawn_weakness(&backward, Color::White).0
        );
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "pawn-weakness tests",
)

path.write_text(text)
