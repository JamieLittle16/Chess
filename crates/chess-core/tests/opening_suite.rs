use std::{collections::HashSet, fs, path::PathBuf};

use chess_core::Position;

const EXPECTED_POSITIONS: usize = 100;

#[test]
fn m3_opening_suite_is_legal_unique_and_nonterminal() {
    let path = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("../../match/openings/m3-uho-lichess-100-v1.epd");
    let content = fs::read_to_string(&path).expect("checked-in M3 opening suite is readable");
    let lines: Vec<_> = content.lines().filter(|line| !line.trim().is_empty()).collect();
    assert_eq!(lines.len(), EXPECTED_POSITIONS);
    assert_eq!(lines.iter().copied().collect::<HashSet<_>>().len(), EXPECTED_POSITIONS);

    for (index, fen) in lines.iter().enumerate() {
        let position = Position::from_fen(fen).unwrap_or_else(|error| {
            panic!("opening {} is invalid FEN {fen:?}: {error:?}", index + 1)
        });
        assert!(
            !position.legal_moves().is_empty(),
            "opening {} is terminal: {fen}",
            index + 1
        );
    }
}
