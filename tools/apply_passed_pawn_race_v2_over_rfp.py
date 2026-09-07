#!/usr/bin/env python3
"""Apply dynamic passed-pawn race evaluation over accepted RFP production."""
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
    "use chess_core::{Color, PieceKind, Position, pawn_attacks};",
    "pawn attack import",
)

text = replace_once(
    text,
    "const FILE_A: u64 = 0x0101_0101_0101_0101;",
    '''const FILE_A: u64 = 0x0101_0101_0101_0101;
const PASSED_PAWN_MASKS: [[u64; 64]; 2] = generate_passed_pawn_masks();
// Static rank bonuses are intentionally smaller than the neutral v1 test. V2 spends most of its
// signal on convertibility: clear path, pawn support/connection and whether the enemy king can
// enter the square before promotion.
const PASSED_BASE_MG: [i32; 8] = [0, 0, 0, 2, 6, 14, 28, 0];
const PASSED_BASE_EG: [i32; 8] = [0, 0, 0, 6, 15, 32, 60, 0];
const PROTECTED_PASSER_MG: [i32; 8] = [0, 0, 0, 2, 4, 8, 14, 0];
const PROTECTED_PASSER_EG: [i32; 8] = [0, 0, 0, 5, 10, 18, 30, 0];
const CONNECTED_PASSER_MG: [i32; 8] = [0, 0, 0, 2, 4, 8, 12, 0];
const CONNECTED_PASSER_EG: [i32; 8] = [0, 0, 0, 4, 8, 14, 24, 0];
const OWN_KING_SUPPORT_EG_BONUS: i32 = 8;
const UNSTOPPABLE_PASSER_MG_BONUS: i32 = 18;
const UNSTOPPABLE_PASSER_EG_BONUS: i32 = 90;''',
    "race constants",
)

text = replace_once(
    text,
    '''    let own_pawns = position.pieces(color, PieceKind::Pawn).raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn).raw();
    for rook in position.pieces(color, PieceKind::Rook) {''',
    '''    let pawns = position.pieces(color, PieceKind::Pawn);
    let own_pawns = pawns.raw();
    let enemy_pawns = position.pieces(color.opposite(), PieceKind::Pawn).raw();

    let mut passed_bits = 0_u64;
    for pawn in pawns {
        let mask = PASSED_PAWN_MASKS[color.index()][usize::from(pawn.index())];
        if enemy_pawns & mask == 0 {
            passed_bits |= 1_u64 << pawn.index();
        }
    }
    for pawn in position.pieces(color, PieceKind::Pawn) {
        if passed_bits & (1_u64 << pawn.index()) == 0 {
            continue;
        }
        let (mg, eg) = passed_pawn_race_score(position, color, pawn, passed_bits);
        middle_game += mg;
        end_game += eg;
    }

    for rook in position.pieces(color, PieceKind::Rook) {''',
    "race scoring",
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
    '''fn passed_pawn_race_score(
    position: &Position,
    color: Color,
    pawn: chess_core::Square,
    passed_bits: u64,
) -> (i32, i32) {
    let rank = relative_rank(color, pawn.rank());
    let mut middle_game = PASSED_BASE_MG[rank];
    let mut end_game = PASSED_BASE_EG[rank];

    let own_pawns = position.pieces(color, PieceKind::Pawn);
    if !(pawn_attacks(color.opposite(), pawn) & own_pawns).is_empty() {
        middle_game += PROTECTED_PASSER_MG[rank];
        end_game += PROTECTED_PASSER_EG[rank];
    }
    if connected_passer(pawn, passed_bits) {
        middle_game += CONNECTED_PASSER_MG[rank];
        end_game += CONNECTED_PASSER_EG[rank];
    }

    let path_clear = promotion_path_is_clear(position, color, pawn);
    if !path_clear {
        middle_game /= 2;
        end_game /= 2;
    }

    if let Some(own_king) = position.pieces(color, PieceKind::King).into_iter().next()
        && king_distance(own_king, pawn) <= 2
    {
        end_game += OWN_KING_SUPPORT_EG_BONUS;
    }

    if path_clear && enemy_king_outside_pawn_square(position, color, pawn) {
        middle_game += UNSTOPPABLE_PASSER_MG_BONUS;
        end_game += UNSTOPPABLE_PASSER_EG_BONUS;
    }

    (middle_game, end_game)
}

fn connected_passer(pawn: chess_core::Square, passed_bits: u64) -> bool {
    let pawn_file = i16::from(pawn.file());
    let pawn_rank = i16::from(pawn.rank());
    let mut bits = passed_bits & !(1_u64 << pawn.index());
    while bits != 0 {
        let index = bits.trailing_zeros() as u8;
        bits &= bits - 1;
        let other_file = i16::from(index & 7);
        let other_rank = i16::from(index >> 3);
        if (other_file - pawn_file).abs() == 1 && (other_rank - pawn_rank).abs() <= 1 {
            return true;
        }
    }
    false
}

fn promotion_path_is_clear(position: &Position, color: Color, pawn: chess_core::Square) -> bool {
    let mut rank = pawn.rank();
    loop {
        rank = match color {
            Color::White => match rank.checked_add(1) {
                Some(next) if next < 8 => next,
                _ => return true,
            },
            Color::Black => match rank.checked_sub(1) {
                Some(next) => next,
                None => return true,
            },
        };
        let Some(square) = chess_core::Square::from_file_rank(pawn.file(), rank) else {
            return true;
        };
        if position.piece_at(square).is_some() {
            return false;
        }
        if rank == 0 || rank == 7 {
            return true;
        }
    }
}

fn enemy_king_outside_pawn_square(
    position: &Position,
    color: Color,
    pawn: chess_core::Square,
) -> bool {
    let Some(enemy_king) = position
        .pieces(color.opposite(), PieceKind::King)
        .into_iter()
        .next()
    else {
        return false;
    };
    let rank = relative_rank(color, pawn.rank());
    let pushes_to_promote = 7_usize.saturating_sub(rank);
    if pushes_to_promote == 0 {
        return false;
    }
    let king_moves_before_promotion = pushes_to_promote.saturating_sub(usize::from(
        position.side_to_move() == color,
    ));
    let promotion_rank = match color {
        Color::White => 7,
        Color::Black => 0,
    };
    let Some(promotion_square) = chess_core::Square::from_file_rank(pawn.file(), promotion_rank)
    else {
        return false;
    };
    king_distance(enemy_king, promotion_square) > king_moves_before_promotion
}

fn king_distance(a: chess_core::Square, b: chess_core::Square) -> usize {
    usize::from(a.file().abs_diff(b.file()).max(a.rank().abs_diff(b.rank())))
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
    "race helpers",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{evaluate, passed_pawn_race_score, piece_structure};",
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn clear_passer_scores_more_than_same_passer_blocked_by_a_piece() {
        let clear = Position::from_fen("k7/8/8/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");
        let blocked =
            Position::from_fen("k7/8/4n3/4P3/8/8/8/7K w - - 0 1").expect("valid FEN");
        assert!(piece_structure(&clear, Color::White).1 > piece_structure(&blocked, Color::White).1);
    }

    #[test]
    fn enemy_king_outside_square_makes_advanced_passer_more_valuable() {
        let outside =
            Position::from_fen("k7/8/4P3/8/8/8/8/7K w - - 0 1").expect("valid FEN");
        let catchable =
            Position::from_fen("8/2k5/4P3/8/8/8/8/7K w - - 0 1").expect("valid FEN");
        assert!(
            piece_structure(&outside, Color::White).1
                > piece_structure(&catchable, Color::White).1
        );
    }

    #[test]
    fn protected_advanced_passer_gets_convertibility_bonus() {
        let protected =
            Position::from_fen("k7/8/4P3/3P4/8/8/8/7K w - - 0 1").expect("valid FEN");
        let bare = Position::from_fen("k7/8/4P3/8/8/8/8/7K w - - 0 1").expect("valid FEN");
        let e6 = chess_core::Square::from_file_rank(4, 5).expect("e6");
        let protected_bits = (1_u64 << e6.index())
            | (1_u64 << chess_core::Square::from_file_rank(3, 4).expect("d5").index());
        let bare_bits = 1_u64 << e6.index();
        assert!(
            passed_pawn_race_score(&protected, Color::White, e6, protected_bits).1
                > passed_pawn_race_score(&bare, Color::White, e6, bare_bits).1
        );
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "race tests",
)

path.write_text(text)
