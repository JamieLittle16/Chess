#!/usr/bin/env python3
"""Apply a gated low-phase endgame mop-up term over accepted RFP."""
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
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let mut phase = 0_i32;''',
    '''    let mut middle_game = 0_i32;
    let mut end_game = 0_i32;
    let mut phase = 0_i32;
    let mut material_by_color = [0_i32; 2];''',
    "material accumulator",
)

text = replace_once(
    text,
    '''            let material = count * PIECE_VALUES[kind.index()];
            middle_game += sign * material;
            end_game += sign * material;''',
    '''            let material = count * PIECE_VALUES[kind.index()];
            material_by_color[color.index()] += material;
            middle_game += sign * material;
            end_game += sign * material;''',
    "material accumulation",
)

text = replace_once(
    text,
    '''    let phase = phase.min(MAX_PHASE);
    let white_minus_black = (middle_game * phase + end_game * (MAX_PHASE - phase)) / MAX_PHASE;''',
    '''    end_game += endgame_mop_up(position, phase, material_by_color);
    let phase = phase.min(MAX_PHASE);
    let white_minus_black = (middle_game * phase + end_game * (MAX_PHASE - phase)) / MAX_PHASE;''',
    "mop-up integration",
)

text = replace_once(
    text,
    "fn piece_structure(position: &Position, color: Color) -> (i32, i32) {",
    r'''fn endgame_mop_up(position: &Position, phase: i32, material_by_color: [i32; 2]) -> i32 {
    // Keep this out of ordinary middlegames. A queen is phase 4 and a rook phase 2, so <= 6
    // captures the classic conversion cases without turning general evaluation into king tropism.
    if phase > 6 {
        return 0;
    }

    let material_delta = material_by_color[Color::White.index()]
        - material_by_color[Color::Black.index()];
    if material_delta.abs() < 400 {
        return 0;
    }

    let winner = if material_delta > 0 {
        Color::White
    } else {
        Color::Black
    };
    let loser = winner.opposite();
    let has_major = !position.pieces(winner, PieceKind::Queen).is_empty()
        || !position.pieces(winner, PieceKind::Rook).is_empty();
    if !has_major {
        return 0;
    }

    let Some(winner_king) = position.pieces(winner, PieceKind::King).into_iter().next() else {
        return 0;
    };
    let Some(loser_king) = position.pieces(loser, PieceKind::King).into_iter().next() else {
        return 0;
    };

    let edge_distance = loser_king
        .file()
        .min(7 - loser_king.file())
        .min(loser_king.rank().min(7 - loser_king.rank()));
    let edge_pressure = 3_i32 - i32::from(edge_distance);
    let king_distance = winner_king
        .file()
        .abs_diff(loser_king.file())
        .max(winner_king.rank().abs_diff(loser_king.rank()));
    let king_closeness = 7_i32 - i32::from(king_distance);
    let bonus = edge_pressure * 18 + king_closeness * 5;

    if winner == Color::White { bonus } else { -bonus }
}

fn piece_structure(position: &Position, color: Color) -> (i32, i32) {''',
    "mop-up helper",
)

text = replace_once(
    text,
    "use super::{evaluate, piece_structure};",
    "use super::{endgame_mop_up, evaluate, piece_structure};",
    "test imports",
)

text = replace_once(
    text,
    '''    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    '''    #[test]
    fn winning_major_piece_endgame_rewards_cornering_and_king_approach() {
        let coordinated =
            Position::from_fen("7k/8/5K2/8/8/8/8/Q7 w - - 0 1").expect("valid FEN");
        let wandering =
            Position::from_fen("8/8/8/8/3k4/8/8/Q6K w - - 0 1").expect("valid FEN");
        let material = [900, 0];
        assert!(endgame_mop_up(&coordinated, 4, material) > endgame_mop_up(&wandering, 4, material));
    }

    #[test]
    fn equal_material_endgame_gets_no_mop_up_bias() {
        let equal =
            Position::from_fen("q6k/8/8/8/8/8/8/Q6K w - - 0 1").expect("valid FEN");
        assert_eq!(endgame_mop_up(&equal, 8, [900, 900]), 0);
    }

    #[test]
    fn endgame_king_is_rewarded_for_centralisation() {''',
    "mop-up tests",
)

path.write_text(text)
