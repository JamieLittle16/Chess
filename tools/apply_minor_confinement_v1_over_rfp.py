#!/usr/bin/env python3
"""Apply severe-only minor-piece confinement penalties over accepted RFP."""
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
    "use chess_core::{Color, PieceKind, Position, Square, bishop_attacks, knight_attacks, pawn_attacks};",
    "confinement imports",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const KNIGHT_ZERO_SAFE_MOBILITY_MG_PENALTY: i32 = 18;
const KNIGHT_ONE_SAFE_MOBILITY_MG_PENALTY: i32 = 8;
const KNIGHT_ZERO_SAFE_MOBILITY_EG_PENALTY: i32 = 12;
const KNIGHT_ONE_SAFE_MOBILITY_EG_PENALTY: i32 = 5;
const BISHOP_ZERO_SAFE_MOBILITY_MG_PENALTY: i32 = 14;
const BISHOP_ONE_SAFE_MOBILITY_MG_PENALTY: i32 = 6;
const BISHOP_ZERO_SAFE_MOBILITY_EG_PENALTY: i32 = 8;
const BISHOP_ONE_SAFE_MOBILITY_EG_PENALTY: i32 = 4;''',
    "confinement constants",
)

text = replace_once(
    text,
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let (confinement_middle_game, confinement_end_game) = minor_confinement(position, color);
    middle_game += confinement_middle_game;
    end_game += confinement_end_game;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    "piece-structure integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn minor_confinement(position: &Position, color: Color) -> (i32, i32) {
    let own_occupancy = position.occupancy(color);
    let occupied = position.occupied();
    let mut enemy_pawn_attacks = chess_core::Bitboard::empty();
    for pawn in position.pieces(color.opposite(), PieceKind::Pawn) {
        enemy_pawn_attacks |= pawn_attacks(color.opposite(), pawn);
    }

    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    for knight in position.pieces(color, PieceKind::Knight) {
        if is_minor_start_square(color, PieceKind::Knight, knight) {
            continue;
        }
        let safe = knight_attacks(knight) & !own_occupancy & !enemy_pawn_attacks;
        match safe.count() {
            0 => {
                middle_game -= KNIGHT_ZERO_SAFE_MOBILITY_MG_PENALTY;
                end_game -= KNIGHT_ZERO_SAFE_MOBILITY_EG_PENALTY;
            }
            1 => {
                middle_game -= KNIGHT_ONE_SAFE_MOBILITY_MG_PENALTY;
                end_game -= KNIGHT_ONE_SAFE_MOBILITY_EG_PENALTY;
            }
            _ => {}
        }
    }

    for bishop in position.pieces(color, PieceKind::Bishop) {
        if is_minor_start_square(color, PieceKind::Bishop, bishop) {
            continue;
        }
        let safe = bishop_attacks(bishop, occupied) & !own_occupancy & !enemy_pawn_attacks;
        match safe.count() {
            0 => {
                middle_game -= BISHOP_ZERO_SAFE_MOBILITY_MG_PENALTY;
                end_game -= BISHOP_ZERO_SAFE_MOBILITY_EG_PENALTY;
            }
            1 => {
                middle_game -= BISHOP_ONE_SAFE_MOBILITY_MG_PENALTY;
                end_game -= BISHOP_ONE_SAFE_MOBILITY_EG_PENALTY;
            }
            _ => {}
        }
    }

    (middle_game, end_game)
}

fn is_minor_start_square(color: Color, kind: PieceKind, square: Square) -> bool {
    let relative_rank = match color {
        Color::White => square.rank(),
        Color::Black => 7 - square.rank(),
    };
    if relative_rank != 0 {
        return false;
    }
    match kind {
        PieceKind::Knight => square.file() == 1 || square.file() == 6,
        PieceKind::Bishop => square.file() == 2 || square.file() == 5,
        _ => false,
    }
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "confinement helpers",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{evaluate, minor_confinement, piece_structure};",
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn severely_confined_knight_is_penalized_without_global_mobility_scoring() {
        let free = Position::from_fen("7k/8/8/8/3N4/8/8/7K w - - 0 1").expect("valid FEN");
        let confined = Position::from_fen("7k/8/8/2p1p3/3N4/2P1P3/8/7K w - - 0 1")
            .expect("valid FEN");
        assert!(
            minor_confinement(&free, Color::White).0
                > minor_confinement(&confined, Color::White).0
        );
    }

    #[test]
    fn undeveloped_starting_minors_are_not_called_trapped() {
        let start = Position::startpos();
        assert_eq!(minor_confinement(&start, Color::White), (0, 0));
        assert_eq!(minor_confinement(&start, Color::Black), (0, 0));
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "confinement tests",
)

path.write_text(text)
