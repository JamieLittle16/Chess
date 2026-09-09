//! Cross-cutting qualification tests for the correctness-critical chess core.
//!
//! These tests intentionally exercise multiple subsystems together. Unit tests next to each
//! implementation remain useful for local failures; this suite is the guardrail for interactions
//! between legal move generation, reversible state transitions, FEN, Zobrist identity and perft.

use chess_core::{
    ChessMove, Position, Undo, generate_legal_moves_mut, generate_legal_tactical_moves_mut, perft,
};

/// Canonical perft positions and counts from the Chess Programming Wiki perft-results suite.
///
/// The ordinary test exercises depths 1..=3 so `cargo test` stays cheap. `deep_perft_qualification`
/// is ignored by default and is run explicitly in release mode by CI.
const STANDARD_PERFT_CASES: [(&str, &str, [u64; 3], u32, u64); 6] = [
    (
        "startpos",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        [20, 400, 8_902],
        5,
        4_865_609,
    ),
    (
        "kiwipete",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        [48, 2_039, 97_862],
        4,
        4_085_603,
    ),
    (
        "position-3",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        [14, 191, 2_812],
        5,
        674_624,
    ),
    (
        "position-4",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        [6, 264, 9_467],
        4,
        422_333,
    ),
    (
        "position-5",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        [44, 1_486, 62_379],
        4,
        2_103_487,
    ),
    (
        "position-6",
        "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
        [46, 2_079, 89_890],
        4,
        3_894_594,
    ),
];

const STATE_MACHINE_ROOTS: [&str; 8] = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
    "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
    "7k/P7/8/8/8/8/8/K7 w - - 0 1",
];

#[test]
fn standard_perft_suite_through_depth_three() {
    for (name, fen, expected, _, _) in STANDARD_PERFT_CASES {
        let position = Position::from_fen(fen).unwrap_or_else(|error| panic!("{name}: {error}"));
        for (offset, nodes) in expected.into_iter().enumerate() {
            let depth = offset as u32 + 1;
            assert_eq!(
                perft(&position, depth),
                nodes,
                "{name} perft mismatch at depth {depth}"
            );
        }
    }
}

#[test]
#[ignore = "release-only CI qualification: intentionally explores ~16M leaf nodes"]
fn deep_perft_qualification() {
    for (name, fen, _, depth, expected) in STANDARD_PERFT_CASES {
        let position = Position::from_fen(fen).unwrap_or_else(|error| panic!("{name}: {error}"));
        assert_eq!(
            perft(&position, depth),
            expected,
            "{name} deep perft mismatch at depth {depth}"
        );
    }
}

#[test]
fn deterministic_state_machine_differential_qualification() {
    const SEEDS: [u64; 2] = [0x9e37_79b9_7f4a_7c15, 0xd1b5_4a32_d192_ed03];
    const MAX_PLIES: usize = 64;

    for (root_index, fen) in STATE_MACHINE_ROOTS.into_iter().enumerate() {
        for seed in SEEDS {
            let root = Position::from_fen(fen).expect("qualification root must parse");
            let mut position = root.clone();
            let mut history: Vec<(ChessMove, Undo, Position)> = Vec::new();
            let mut rng = seed ^ (root_index as u64).wrapping_mul(0xa076_1d64_78bd_642f);

            for ply in 0..MAX_PLIES {
                let label = format!("root={root_index} seed={seed:#x} ply={ply}");
                assert_state_consistent(&mut position, &label);
                assert_all_legal_transitions_match_reference(&position, &label);

                let moves = position.legal_moves();
                if moves.is_empty() {
                    break;
                }

                let before = position.clone();
                let mv = moves[next_random(&mut rng) as usize % moves.len()];
                let expected = position
                    .reference_after(mv)
                    .unwrap_or_else(|| panic!("reference rejected legal move {mv:?}: {label}"));
                let undo = position.make_move(mv);

                assert_eq!(position, expected, "forward transition mismatch: {label}");
                assert_eq!(
                    position.zobrist_key(),
                    position.recomputed_zobrist_key(),
                    "incremental Zobrist mismatch after {mv:?}: {label}"
                );

                history.push((mv, undo, before));
            }

            while let Some((mv, undo, before)) = history.pop() {
                position.unmake_move(mv, undo);
                assert_eq!(position, before, "undo mismatch for {mv:?}");
                assert_eq!(position.zobrist_key(), position.recomputed_zobrist_key());
            }

            assert_eq!(position, root, "complete playout did not round-trip");
        }
    }
}

fn assert_state_consistent(position: &mut Position, label: &str) {
    assert_eq!(
        position.zobrist_key(),
        position.recomputed_zobrist_key(),
        "incremental Zobrist mismatch: {label}"
    );

    let fen = position.to_fen();
    let reparsed = Position::from_fen(&fen)
        .unwrap_or_else(|error| panic!("generated FEN failed to parse ({label}): {error}: {fen}"));
    assert_eq!(*position, reparsed, "FEN round-trip mismatch: {label}");

    let before = position.clone();
    let full = generate_legal_moves_mut(position);
    assert_eq!(*position, before, "full movegen mutated position: {label}");
    assert_eq!(
        full.as_slice(),
        position.legal_moves().as_slice(),
        "mutable and immutable movegen disagree: {label}"
    );

    let tactical = generate_legal_tactical_moves_mut(position);
    assert_eq!(
        *position, before,
        "tactical movegen mutated position: {label}"
    );
    let expected_tactical: Vec<_> = full
        .as_slice()
        .iter()
        .copied()
        .filter(|mv| mv.kind().is_capture() || mv.kind().is_promotion())
        .collect();
    assert_eq!(
        tactical.len(),
        expected_tactical.len(),
        "tactical move count mismatch: {label}"
    );
    for &mv in &tactical {
        assert!(
            expected_tactical.contains(&mv),
            "tactical generator produced unexpected {mv:?}: {label}"
        );
    }
}

fn assert_all_legal_transitions_match_reference(position: &Position, label: &str) {
    for &mv in &position.legal_moves() {
        let expected = position
            .reference_after(mv)
            .unwrap_or_else(|| panic!("reference rejected legal move {mv:?}: {label}"));
        let mut actual = position.clone();
        let undo = actual.make_move(mv);
        assert_eq!(actual, expected, "make_move mismatch for {mv:?}: {label}");
        actual.unmake_move(mv, undo);
        assert_eq!(&actual, position, "unmake_move mismatch for {mv:?}: {label}");
    }
}

fn next_random(state: &mut u64) -> u64 {
    // SplitMix64: deterministic, dependency-free and sufficient for reproducible test coverage.
    *state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut value = *state;
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}
