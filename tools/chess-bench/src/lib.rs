//! Deterministic reference-search benchmark used for behavioral regression detection.
//!
//! This tool deliberately excludes wall-clock acceptance thresholds from CI. Shared runners are
//! suitable for checking a deterministic search signature, not for making performance claims.

use chess_core::Position;
use chess_search::Searcher;

/// V8 adds the accepted E4 bishop-pair and rook open/semi-open-file terms on top of V7's tapered
/// geometric PSQT and two-slot quiet killer ordering. The reviewed five-case report is:
///
/// - startpos d3: score +24, 649 nodes, 22 TT hits, best raw move 82 (`Nb1-c3`);
/// - Kiwipete d2: score +17, 1,137 nodes, 2 TT hits, best raw move 3,427;
/// - mate-net d2: mate score 29,999, 72 nodes, 1 TT hit, best raw move 3,446;
/// - en-passant d3: score +167, 63 nodes, 7 TT hits, best raw move 22,827;
/// - promotion d2: score +886, 62 nodes, 2 TT hits, best raw move 9 (`Ka1-b2`).
///
/// E4 was first screened against exact V7 production and then qualified twice from materialized
/// source. The original 200-game suite scored 60W/95D/45L (+26.11 +/- 32.35 Elo, LOS 94.43%).
/// Because that was narrowly below the preferred confidence line, a fresh 100-position UHO holdout
/// was selected deterministically from the pinned 2,632,036-position Stockfish source while
/// explicitly excluding every source line used by the original suite. On that disjoint 200-game
/// holdout E4 scored 70W/80D/50L (+34.86 +/- 35.54 Elo, LOS 97.40%). This independent validation
/// accepts the evaluator drift as the new production baseline.
pub const SUITE_NAME: &str = "reference-search-v8";
/// Reviewed after the H1-accepted V14 Search-v2 promotion. The case set is unchanged;
/// only the deterministic search trace changed. Frozen M6 SPRT: 132W/70D/6L over 208 games,
/// +243.97 +/- 37.36 Elo, LLR 2.95 beyond the 2.94 H1 boundary.
pub const EXPECTED_SIGNATURE: u64 = 0x3f02_47ab_79ca_e85a;

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
