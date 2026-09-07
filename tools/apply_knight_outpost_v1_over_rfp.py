#!/usr/bin/env python3
"""Apply a cheap supported, pawn-unchallengeable knight-outpost term over accepted RFP."""
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
    "outpost imports",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const KNIGHT_OUTPOST_MG_BONUS: [i32; 8] = [0, 0, 0, 8, 14, 18, 0, 0];
const KNIGHT_OUTPOST_EG_BONUS: [i32; 8] = [0, 0, 0, 4, 7, 9, 0, 0];''',
    "outpost constants",
)

text = replace_once(
    text,
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let (outpost_middle_game, outpost_end_game) = knight_outposts(position, color);
    middle_game += outpost_middle_game;
    end_game += outpost_end_game;

    if position.pieces(color, PieceKind::Bishop).count() >= 2 {''',
    "piece-structure integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn knight_outposts(position: &Position, color: Color) -> (i32, i32) {
    let own_pawns = position.pieces(color, PieceKind::Pawn);
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;

    for knight in position.pieces(color, PieceKind::Knight) {
        let rank = relative_rank(color, knight.rank());
        if KNIGHT_OUTPOST_MG_BONUS[rank] == 0 {
            continue;
        }

        // A real outpost must already be pawn-supported.
        if (pawn_attacks(color.opposite(), knight) & own_pawns).is_empty() {
            continue;
        }

        // And no enemy pawn on an adjacent file may still be able to advance to challenge it.
        if enemy_pawn_can_challenge(color, knight, enemy_pawns) {
            continue;
        }

        middle_game += KNIGHT_OUTPOST_MG_BONUS[rank];
        end_game += KNIGHT_OUTPOST_EG_BONUS[rank];
    }

    (middle_game, end_game)
}

fn enemy_pawn_can_challenge(
    color: Color,
    square: Square,
    enemy_pawns: chess_core::Bitboard,
) -> bool {
    for pawn in enemy_pawns {
        if pawn.file().abs_diff(square.file()) != 1 {
            continue;
        }
        match color {
            Color::White if pawn.rank() > square.rank() => return true,
            Color::Black if pawn.rank() < square.rank() => return true,
            _ => {}
        }
    }
    false
}

#[inline]
const fn relative_rank(color: Color, rank: u8) -> usize {
    match color {
        Color::White => rank as usize,
        Color::Black => (7 - rank) as usize,
    }
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "outpost helpers",
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
    "use super::{evaluate, knight_outposts, piece_structure};",
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn supported_unchallengeable_knight_is_an_outpost() {
        let outpost = Position::from_fen("7k/8/8/3N4/2P5/8/8/7K w - - 0 1")
            .expect("valid FEN");
        let unsupported = Position::from_fen("7k/8/8/3N4/8/8/8/7K w - - 0 1")
            .expect("valid FEN");
        assert!(
            knight_outposts(&outpost, Color::White).0
                > knight_outposts(&unsupported, Color::White).0
        );
    }

    #[test]
    fn enemy_pawn_that_can_challenge_removes_outpost_bonus() {
        let stable = Position::from_fen("7k/8/8/3N4/2P5/8/8/7K w - - 0 1")
            .expect("valid FEN");
        let challenge = Position::from_fen("7k/8/4p3/3N4/2P5/8/8/7K w - - 0 1")
            .expect("valid FEN");
        assert!(
            knight_outposts(&stable, Color::White).0
                > knight_outposts(&challenge, Color::White).0
        );
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "outpost tests",
)

path.write_text(text)
