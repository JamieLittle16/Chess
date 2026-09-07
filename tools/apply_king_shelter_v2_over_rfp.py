#!/usr/bin/env python3
from pathlib import Path

path = Path("crates/chess-eval/src/lib.rs")
text = path.read_text()

old = "use chess_core::{Color, PieceKind, Position};"
new = "use chess_core::{CastlingRights, Color, PieceKind, Position};"
if old not in text:
    raise SystemExit("import anchor missing")
text = text.replace(old, new, 1)

anchor = "const FILE_A: u64 = 0x0101_0101_0101_0101;\n"
insert = anchor + """

// M4 king-shelter v2 deliberately avoids the failed E5 all-attack-map model.  It only reads pawn
// bitboards, king placement and castling rights: intact cover is rewarded, open files and nearby
// enemy pawn storms are penalized, and preserving the option to castle has a small MG value.
const CASTLING_RIGHT_MG_BONUS: i32 = 4;
const FIRST_SHIELD_PAWN_MG_BONUS: i32 = 10;
const SECOND_SHIELD_PAWN_MG_BONUS: i32 = 4;
const MISSING_KING_FILE_PAWN_MG_PENALTY: i32 = 10;
const MISSING_ADJACENT_FILE_PAWN_MG_PENALTY: i32 = 5;
const FULLY_OPEN_KING_ZONE_FILE_MG_PENALTY: i32 = 5;
const PAWN_STORM_MG_PENALTY: [i32; 8] = [0, 28, 22, 14, 8, 4, 0, 0];
"""
if anchor not in text:
    raise SystemExit("constant anchor missing")
text = text.replace(anchor, insert, 1)

anchor = """        let (structure_middle_game, structure_end_game) = piece_structure(position, color);\n        middle_game += sign * structure_middle_game;\n        end_game += sign * structure_end_game;\n"""
insert = """        let (structure_middle_game, structure_end_game) = piece_structure(position, color);\n        middle_game += sign * (structure_middle_game + king_shelter_middle_game(position, color));\n        end_game += sign * structure_end_game;\n"""
if anchor not in text:
    raise SystemExit("evaluation anchor missing")
text = text.replace(anchor, insert, 1)

anchor = "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {\n"
function = r'''fn king_shelter_middle_game(position: &Position, color: Color) -> i32 {
    let Some(king) = position.pieces(color, PieceKind::King).into_iter().next() else {
        return 0;
    };
    let relative_king_rank = match color {
        Color::White => king.rank(),
        Color::Black => 7 - king.rank(),
    };

    // Once the king has walked into the board, the existing king PSQT is a better signal than a
    // home-shelter model.  This also keeps the term naturally opening/middlegame-specific.
    if relative_king_rank > 1 {
        return 0;
    }

    let own_pawns = position.pieces(color, PieceKind::Pawn).raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn);
    let enemy_pawn_bits = enemy_pawns.raw();
    let mut score = 0_i32;

    let rights = position.castling_rights();
    let (king_side, queen_side) = match color {
        Color::White => (CastlingRights::WHITE_KING, CastlingRights::WHITE_QUEEN),
        Color::Black => (CastlingRights::BLACK_KING, CastlingRights::BLACK_QUEEN),
    };
    if rights.contains(king_side) {
        score += CASTLING_RIGHT_MG_BONUS;
    }
    if rights.contains(queen_side) {
        score += CASTLING_RIGHT_MG_BONUS;
    }

    let first_rank = match color {
        Color::White => king.rank().checked_add(1),
        Color::Black => king.rank().checked_sub(1),
    };
    let second_rank = match color {
        Color::White => king.rank().checked_add(2),
        Color::Black => king.rank().checked_sub(2),
    };

    let first_file = king.file().saturating_sub(1);
    let last_file = king.file().saturating_add(1).min(7);
    let mut file = first_file;
    while file <= last_file {
        let file_mask = FILE_A << u32::from(file);
        let own_on_file = own_pawns & file_mask;
        let enemy_on_file = enemy_pawn_bits & file_mask;
        let file_distance = file.abs_diff(king.file());

        let first_square = first_rank
            .filter(|&rank| rank < 8)
            .and_then(|rank| chess_core::Square::from_file_rank(file, rank));
        let second_square = second_rank
            .filter(|&rank| rank < 8)
            .and_then(|rank| chess_core::Square::from_file_rank(file, rank));

        if first_square.is_some_and(|square| own_pawns & (1_u64 << square.index()) != 0) {
            score += FIRST_SHIELD_PAWN_MG_BONUS;
        } else if second_square.is_some_and(|square| own_pawns & (1_u64 << square.index()) != 0) {
            score += SECOND_SHIELD_PAWN_MG_BONUS;
        } else {
            score -= if file_distance == 0 {
                MISSING_KING_FILE_PAWN_MG_PENALTY
            } else {
                MISSING_ADJACENT_FILE_PAWN_MG_PENALTY
            };
        }

        if own_on_file == 0 && enemy_on_file == 0 {
            score -= FULLY_OPEN_KING_ZONE_FILE_MG_PENALTY;
        }

        for pawn in enemy_pawns {
            if pawn.file() != file {
                continue;
            }
            let defender_relative_rank = match color {
                Color::White => usize::from(pawn.rank()),
                Color::Black => usize::from(7 - pawn.rank()),
            };
            score -= PAWN_STORM_MG_PENALTY[defender_relative_rank];
        }

        if file == last_file {
            break;
        }
        file += 1;
    }

    score
}

'''
if anchor not in text:
    raise SystemExit("piece_structure anchor missing")
text = text.replace(anchor, function + anchor, 1)

old = "use super::{evaluate, piece_structure};"
new = "use super::{evaluate, king_shelter_middle_game, piece_structure};"
if old not in text:
    raise SystemExit("test import anchor missing")
text = text.replace(old, new, 1)

anchor = """    #[test]\n    fn endgame_king_is_rewarded_for_centralisation() {\n        let central = Position::from_fen(\"7k/8/8/8/3K4/8/8/8 w - - 0 1\").expect(\"valid FEN\");\n        let corner = Position::from_fen(\"7k/8/8/8/8/8/8/K7 w - - 0 1\").expect(\"valid FEN\");\n        assert!(evaluate(&central) > evaluate(&corner));\n    }\n"""
tests = anchor + r'''

    #[test]
    fn intact_castled_pawn_cover_is_safer_than_an_exposed_king() {
        let shielded =
            Position::from_fen("7k/8/8/8/8/8/5PPP/6K1 w - - 0 1").expect("valid FEN");
        let exposed = Position::from_fen("7k/8/8/8/8/8/8/6K1 w - - 0 1").expect("valid FEN");
        assert!(
            king_shelter_middle_game(&shielded, Color::White)
                > king_shelter_middle_game(&exposed, Color::White)
        );
    }

    #[test]
    fn nearby_enemy_pawn_storm_reduces_king_safety() {
        let distant = Position::from_fen("7k/5p2/8/8/8/8/5PPP/6K1 w - - 0 1")
            .expect("valid FEN");
        let storm = Position::from_fen("7k/8/8/8/5p2/8/5PPP/6K1 w - - 0 1")
            .expect("valid FEN");
        assert!(
            king_shelter_middle_game(&distant, Color::White)
                > king_shelter_middle_game(&storm, Color::White)
        );
    }

    #[test]
    fn retaining_castling_rights_has_small_option_value() {
        let rights = Position::from_fen("4k3/8/8/8/8/8/PPP2PPP/R3K2R w KQ - 0 1")
            .expect("valid FEN");
        let lost = Position::from_fen("4k3/8/8/8/8/8/PPP2PPP/R3K2R w - - 0 1")
            .expect("valid FEN");
        assert!(
            king_shelter_middle_game(&rights, Color::White)
                > king_shelter_middle_game(&lost, Color::White)
        );
    }
'''
if anchor not in text:
    raise SystemExit("test insertion anchor missing")
text = text.replace(anchor, tests, 1)

path.write_text(text)
