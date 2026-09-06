#!/usr/bin/env python3
"""Apply bishop-pair and rook-file evaluation directly over accepted E1 main."""
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
    "const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);\n",
    "const EG_PSQT: [[i16; 64]; 6] = generate_psqt(true);\n\n"
    "const BISHOP_PAIR_MG_BONUS: i32 = 30;\n"
    "const BISHOP_PAIR_EG_BONUS: i32 = 45;\n"
    "const ROOK_OPEN_FILE_MG_BONUS: i32 = 16;\n"
    "const ROOK_OPEN_FILE_EG_BONUS: i32 = 12;\n"
    "const ROOK_SEMI_OPEN_FILE_MG_BONUS: i32 = 8;\n"
    "const ROOK_SEMI_OPEN_FILE_EG_BONUS: i32 = 6;\n"
    "const FILE_A: u64 = 0x0101_0101_0101_0101;\n",
    "constants",
)
text = replace_once(
    text,
    "    for color in Color::ALL {\n        let sign = if color == Color::White { 1 } else { -1 };\n        for kind in PieceKind::ALL {",
    "    for color in Color::ALL {\n        let sign = if color == Color::White { 1 } else { -1 };\n"
    "        let (structure_middle_game, structure_end_game) = piece_structure(position, color);\n"
    "        middle_game += sign * structure_middle_game;\n"
    "        end_game += sign * structure_end_game;\n\n"
    "        for kind in PieceKind::ALL {",
    "accumulation",
)
anchor = "#[inline]\nconst fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {"
helper = '''fn piece_structure(position: &Position, color: Color) -> (i32, i32) {
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
const fn relative_square_index(color: Color, file: u8, rank: u8) -> usize {'''
text = replace_once(text, anchor, helper, "helper")
text = replace_once(
    text,
    "    use chess_core::Position;\n\n    use super::evaluate;",
    "    use chess_core::{Color, Position};\n\n    use super::{evaluate, piece_structure};",
    "test imports",
)
text = replace_once(
    text,
    "    #[test]\n    fn endgame_king_is_rewarded_for_centralisation() {",
    '''    #[test]
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
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "tests",
)
path.write_text(text)
