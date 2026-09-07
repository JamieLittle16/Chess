#!/usr/bin/env python3
"""Apply only the old E3 passed-pawn term over accepted RFP production."""
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
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();
const PASSED_PAWN_MG_BONUS: [i32; 8] = [0, 0, 0, 5, 12, 25, 45, 0];
const PASSED_PAWN_EG_BONUS: [i32; 8] = [0, 0, 0, 10, 25, 50, 90, 0];''',
    "passed-pawn constants",
)

text = replace_once(
    text,
    '''    let own_pawns = position.pieces(color, PieceKind::Pawn).raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn).raw();
    for rook in position.pieces(color, PieceKind::Rook) {''',
    '''    let pawns = position.pieces(color, PieceKind::Pawn);
    let own_pawns = pawns.raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn).raw();

    for pawn in pawns {
        let passed_mask = PASSED_PAWN_MASKS[color.index()][usize::from(pawn.index())];
        if enemy_pawns & passed_mask == 0 {
            let rank = relative_rank(color, pawn.rank());
            middle_game += PASSED_PAWN_MG_BONUS[rank];
            end_game += PASSED_PAWN_EG_BONUS[rank];
        }
    }

    for rook in position.pieces(color, PieceKind::Rook) {''',
    "passed-pawn scoring",
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
}

const fn generate_psqt''',
    '''#[inline]
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

const fn generate_psqt''',
    "passed-pawn masks",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn passed_pawn_term_distinguishes_a_real_passer_from_a_blocked_file() {
        let passed = Position::from_fen("7k/8/8/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");
        let blocked =
            Position::from_fen("7k/8/4p3/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");

        assert_eq!(piece_structure(&passed, Color::White), (12, 25));
        assert_eq!(piece_structure(&blocked, Color::White), (0, 0));
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "passed-pawn test",
)

path.write_text(text)
