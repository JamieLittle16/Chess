#!/usr/bin/env python3
"""Apply heavy-piece-access king danger v3 over accepted LMR production."""
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
    "use chess_core::{Color, PieceKind, Position, king_attacks, queen_attacks, rook_attacks};",
    "king danger imports",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const HEAVY_KING_DANGER_CAP_MG: i32 = 84;
const QUEEN_KING_ZONE_HIT_UNITS: i32 = 3;
const ROOK_KING_ZONE_HIT_UNITS_WITH_QUEEN: i32 = 2;
const ROOK_KING_ZONE_HIT_UNITS_WITHOUT_QUEEN: i32 = 1;''',
    "king danger constants",
)

text = replace_once(
    text,
    '''        let (structure_middle_game, structure_end_game) = piece_structure(position, color);
        middle_game += sign * structure_middle_game;
        end_game += sign * structure_end_game;''',
    '''        let (structure_middle_game, structure_end_game) = piece_structure(position, color);
        middle_game += sign
            * (structure_middle_game + heavy_piece_king_danger_middle_game(position, color));
        end_game += sign * structure_end_game;''',
    "king danger integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn heavy_piece_king_danger_middle_game(position: &Position, color: Color) -> i32 {
    let enemy = color.opposite();
    let queens = position.pieces(enemy, PieceKind::Queen);
    let rooks = position.pieces(enemy, PieceKind::Rook);
    if queens.is_empty() && rooks.is_empty() {
        return 0;
    }

    let Some(king) = position.pieces(color, PieceKind::King).into_iter().next() else {
        return 0;
    };
    let zone = king_attacks(king);
    let occupied = position.occupied();
    let queen_present = !queens.is_empty();
    let mut pressure_units = 0_i32;

    for queen in queens {
        pressure_units += (queen_attacks(queen, occupied) & zone).count() as i32
            * QUEEN_KING_ZONE_HIT_UNITS;
    }
    let rook_weight = if queen_present {
        ROOK_KING_ZONE_HIT_UNITS_WITH_QUEEN
    } else {
        ROOK_KING_ZONE_HIT_UNITS_WITHOUT_QUEEN
    };
    for rook in rooks {
        pressure_units += (rook_attacks(rook, occupied) & zone).count() as i32 * rook_weight;
    }
    if pressure_units == 0 {
        return 0;
    }

    // Shelter is not independently scored. It only magnifies real heavy-piece access into the
    // king zone, which avoids paying a generic pawn-cover bonus that stronger search already
    // absorbed in v2.
    let own_pawns = position.pieces(color, PieceKind::Pawn).raw();
    let all_pawns = own_pawns | position.pieces(enemy, PieceKind::Pawn).raw();
    let first_rank = match color {
        Color::White => king.rank().checked_add(1),
        Color::Black => king.rank().checked_sub(1),
    };
    let second_rank = match color {
        Color::White => king.rank().checked_add(2),
        Color::Black => king.rank().checked_sub(2),
    };
    let mut exposure = 0_i32;
    let first_file = king.file().saturating_sub(1);
    let last_file = king.file().saturating_add(1).min(7);
    let mut file = first_file;
    while file <= last_file {
        let first = first_rank
            .filter(|&rank| rank < 8)
            .and_then(|rank| chess_core::Square::from_file_rank(file, rank));
        let second = second_rank
            .filter(|&rank| rank < 8)
            .and_then(|rank| chess_core::Square::from_file_rank(file, rank));
        let covered = first.is_some_and(|sq| own_pawns & (1_u64 << sq.index()) != 0)
            || second.is_some_and(|sq| own_pawns & (1_u64 << sq.index()) != 0);
        if !covered {
            exposure += if file == king.file() { 2 } else { 1 };
        }
        let file_mask = FILE_A << u32::from(file);
        if all_pawns & file_mask == 0 {
            exposure += 1;
        }
        if file == last_file {
            break;
        }
        file += 1;
    }

    let danger = pressure_units * (2 + exposure);
    -danger.min(HEAVY_KING_DANGER_CAP_MG)
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "king danger helper",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{evaluate, heavy_piece_king_danger_middle_game, piece_structure};",
    "king danger test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn exposed_king_is_only_penalized_when_enemy_heavy_piece_has_zone_access() {
        let access = Position::from_fen("6qk/8/8/8/8/8/8/6K1 w - - 0 1").expect("valid FEN");
        let blocked =
            Position::from_fen("6qk/8/8/8/8/6P1/8/6K1 w - - 0 1").expect("valid FEN");
        assert!(
            heavy_piece_king_danger_middle_game(&access, Color::White)
                < heavy_piece_king_danger_middle_game(&blocked, Color::White)
        );
    }

    #[test]
    fn missing_shelter_without_enemy_heavy_pieces_has_no_v3_penalty() {
        let bare = Position::from_fen("7k/8/8/8/8/8/8/6K1 w - - 0 1").expect("valid FEN");
        assert_eq!(heavy_piece_king_danger_middle_game(&bare, Color::White), 0);
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "king danger tests",
)

path.write_text(text)
