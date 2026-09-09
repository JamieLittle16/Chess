use std::collections::HashSet;

use chess_core::{FenError, MoveKind, Position};

#[test]
fn fen_parser_rejects_zero_width_digits_and_malformed_en_passant_fields() {
    assert_eq!(
        Position::from_fen("7k/8/8/8/8/8/8/K07 w - - 0 1"),
        Err(FenError::RankWidth),
        "FEN rank compression must use digits 1 through 8"
    );

    for ep in ["a6x", "z6", "a?", "a4"] {
        let fen = format!("7k/8/8/8/8/8/8/K7 w - {ep} 0 1");
        assert_eq!(
            Position::from_fen(&fen),
            Err(FenError::InvalidEnPassant),
            "malformed en-passant field must be rejected: {ep}"
        );
    }
}

#[test]
fn insufficient_material_counts_minor_pieces_symmetrically() {
    let black_knight =
        Position::from_fen("6nk/8/8/8/8/8/8/K7 w - - 0 1").expect("valid K versus K+N");
    assert!(black_knight.is_insufficient_material());

    let opposite_knights =
        Position::from_fen("6nk/8/8/8/8/8/8/KN6 w - - 0 1").expect("valid K+N versus K+N");
    assert!(
        !opposite_knights.is_insufficient_material(),
        "two knights on the board are not an automatic dead-position class"
    );

    let opposite_colour_bishops_same_side =
        Position::from_fen("7k/8/8/8/8/8/8/KBB5 w - - 0 1").expect("valid two-bishop position");
    assert!(
        !opposite_colour_bishops_same_side.is_insufficient_material(),
        "bishops covering both square colours retain mating material"
    );
}

#[test]
fn ghost_en_passant_target_never_creates_a_legal_capture_or_repetition_distinction() {
    let ghost = Position::from_fen("7k/8/8/4P3/8/8/8/K7 w - d6 0 1").expect("valid ghost-EP FEN");
    let plain = Position::from_fen("7k/8/8/4P3/8/8/8/K7 w - - 0 1").expect("valid control FEN");

    assert!(
        ghost
            .legal_moves()
            .iter()
            .all(|mv| mv.kind() != MoveKind::EnPassant),
        "an EP target without the capturable pawn behind it must not create a move"
    );
    assert_eq!(
        ghost.repetition_key(),
        plain.repetition_key(),
        "unusable EP metadata is excluded from repetition identity"
    );
}

#[test]
fn exact_castling_rights_have_distinct_transposition_identities() {
    let rights = [
        "-", "K", "Q", "KQ", "k", "Kk", "Qk", "KQk", "q", "Kq", "Qq", "KQq", "kq", "Kkq", "Qkq",
        "KQkq",
    ];
    let mut keys = HashSet::new();

    for rights in rights {
        let fen = format!("r3k2r/8/8/8/8/8/8/R3K2R w {rights} - 0 1");
        let position = Position::from_fen(&fen).expect("castling-rights FEN must parse");
        assert!(
            keys.insert(position.zobrist_key().raw()),
            "distinct exact castling-right sets must not collapse in the TT key: {rights}"
        );
    }

    assert_eq!(keys.len(), 16);
}

#[test]
fn exact_en_passant_targets_have_distinct_transposition_identities() {
    let mut keys = HashSet::new();

    for file in b'a'..=b'h' {
        let target = format!("{}6", char::from(file));
        let fen = format!("7k/8/8/8/8/8/8/K7 w - {target} 0 1");
        let position = Position::from_fen(&fen).expect("exact EP-target FEN must parse");
        assert!(
            keys.insert(position.zobrist_key().raw()),
            "distinct exact EP targets must not collapse in the TT key: {target}"
        );
    }

    assert_eq!(keys.len(), 8);
}
