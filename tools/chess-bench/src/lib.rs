//! Deterministic reference-search benchmark used for behavioral regression detection.
//!
//! This tool deliberately excludes wall-clock acceptance thresholds from CI. Shared runners are
//! suitable for checking a deterministic search signature, not for making performance claims.

use chess_core::Position;
use chess_search::Searcher;

/// V9 promotes the V15 qsearch check-evasion correction on top of the H1-accepted V14 Search-v2
/// baseline. The case set is unchanged; the reviewed five-case report is:
///
/// - startpos d3: score +24, 647 nodes, 22 TT hits, best raw move 82 (`Nb1-c3`);
/// - Kiwipete d2: score +17, 1,224 nodes, 1 TT hit, best raw move 17,192;
/// - mate-net d2: mate score 29,999, 72 nodes, 1 TT hit, best raw move 3,446;
/// - en-passant d3: score +167, 63 nodes, 7 TT hits, best raw move 22,827;
/// - promotion d2: score +886, 63 nodes, 2 TT hits, best raw move 9 (`Ka1-b2`).
///
/// The V15 correction leaves the ordinary four-ply qsearch tactical ceiling unchanged at non-check
/// nodes, but forbids terminating at that local ceiling while the side to move is still in check.
/// Checked nodes therefore resolve legal evasions until a non-check node (or the global search-ply
/// guard) is reached. The exact source change was qualified against V14 over two paired suites:
/// 100 fixed-node games scored 26W/58D/16L (+34.86 +/- 39.08 Elo), and 100 equal-time 1+0.01 games
/// scored 23W/59D/18L (+17.39 +/- 40.28 Elo). Fixed-node NPS was effectively unchanged.
pub const SUITE_NAME: &str = "reference-search-v9";
pub const EXPECTED_SIGNATURE: u64 = 0xeba4_10d3_1bee_522d;

const FNV_OFFSET: u64 = 0xcbf2_9ce4_8422_2325;
const FNV_PRIME: u64 = 0x0000_0100_0000_01b3;

const CASES: [BenchSpec; 5] = [
    BenchSpec {
        name: "startpos",
        fen: "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        depth: 3,
    },
    BenchSpec {
        name: "kiwipete",
        fen: "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        depth: 2,
    },
    BenchSpec {
        name: "mate-net",
        fen: "7k/5Q2/6K1/8/8/8/8/8 w - - 0 1",
        depth: 2,
    },
    BenchSpec {
        name: "en-passant",
        fen: "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
        depth: 3,
    },
    BenchSpec {
        name: "promotion",
        fen: "7k/P7/8/8/8/8/8/K7 w - - 0 1",
        depth: 2,
    },
];

#[derive(Clone, Copy)]
struct BenchSpec {
    name: &'static str,
    fen: &'static str,
    depth: u8,
}

/// Deterministic result for one benchmark case.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BenchCaseResult {
    pub name: &'static str,
    pub depth: u8,
    pub score: i32,
    pub nodes: u64,
    pub tt_hits: u64,
    pub best_move_raw: Option<u16>,
}

/// Complete deterministic benchmark result.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct BenchReport {
    pub suite: &'static str,
    pub cases: Vec<BenchCaseResult>,
    pub signature: u64,
}

/// Run the versioned reference suite from cold search state for each position.
#[must_use]
pub fn run_reference_suite() -> BenchReport {
    let mut cases = Vec::with_capacity(CASES.len());
    for spec in CASES {
        let mut position = Position::from_fen(spec.fen).expect("benchmark FEN is repository-owned");
        let mut searcher = Searcher::default();
        let result = searcher.iterative_deepening(&mut position, spec.depth);
        cases.push(BenchCaseResult {
            name: spec.name,
            depth: spec.depth,
            score: result.score,
            nodes: result.nodes,
            tt_hits: result.tt_hits,
            best_move_raw: result.best_move.map(|mv| mv.raw()),
        });
    }

    let signature = signature(&cases);
    BenchReport {
        suite: SUITE_NAME,
        cases,
        signature,
    }
}

fn signature(cases: &[BenchCaseResult]) -> u64 {
    let mut hash = FNV_OFFSET;
    for case in cases {
        hash = mix_bytes(hash, case.name.as_bytes());
        hash = mix_u64(hash, u64::from(case.depth));
        hash = mix_u64(hash, case.score as i64 as u64);
        hash = mix_u64(hash, case.nodes);
        hash = mix_u64(hash, case.tt_hits);
        hash = mix_u64(hash, u64::from(case.best_move_raw.unwrap_or(u16::MAX)));
    }
    hash
}

fn mix_u64(hash: u64, value: u64) -> u64 {
    mix_bytes(hash, &value.to_le_bytes())
}

fn mix_bytes(mut hash: u64, bytes: &[u8]) -> u64 {
    for &byte in bytes {
        hash ^= u64::from(byte);
        hash = hash.wrapping_mul(FNV_PRIME);
    }
    hash
}

#[cfg(test)]
mod tests {
    use super::{EXPECTED_SIGNATURE, run_reference_suite};

    #[test]
    fn suite_is_deterministic_within_the_same_build() {
        assert_eq!(run_reference_suite(), run_reference_suite());
    }

    #[test]
    fn suite_matches_the_reviewed_reference_signature() {
        let report = run_reference_suite();
        assert_eq!(
            report.signature, EXPECTED_SIGNATURE,
            "reference benchmark drifted:\n{report:#?}"
        );
        assert!(report.cases.iter().all(|case| case.nodes > 0));
        assert!(report.cases.iter().all(|case| case.best_move_raw.is_some()));
    }
}
