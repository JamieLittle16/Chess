#!/usr/bin/env python3
"""Instrument Rust V15's static-evaluation decision boundaries for offline distillation.

The probe is compiled only with the existing `search-trace` feature. Normal engine builds are
untouched. Records retain the alpha/beta window and search context at every static-eval use that can
change a pruning/cutoff decision, rather than merely dumping unrelated leaf FENs.
"""
from pathlib import Path

search = Path("crates/chess-search/src/lib.rs")
s = search.read_text()

anchor = "mod history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n"
replacement = "#[cfg(feature = \"search-trace\")]\nmod decision_trace;\nmod history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n"
if s.count(anchor) != 1:
    raise SystemExit(f"module anchor count={s.count(anchor)}")
s = s.replace(anchor, replacement, 1)

anchor = "            Some(self.leaf_evaluate(position))\n"
replacement = """            let static_eval = self.leaf_evaluate(position);
            #[cfg(feature = \"search-trace\")]
            decision_trace::observe(position, \"rfp\", depth, ply, 0, alpha, beta, static_eval);
            Some(static_eval)
"""
if s.count(anchor) != 1:
    raise SystemExit(f"RFP leaf anchor count={s.count(anchor)}")
s = s.replace(anchor, replacement, 1)
search.write_text(s)

qpath = Path("crates/chess-search/src/quiescence.rs")
q = qpath.read_text()

anchor = """            return Some(self.leaf_evaluate(position));
        }

        // Legal terminal detection happened above."""
replacement = """            let static_eval = self.leaf_evaluate(position);
            #[cfg(feature = \"search-trace\")]
            decision_trace::observe(position, \"qstable\", 0, ply, qply, alpha, beta, static_eval);
            return Some(static_eval);
        }

        // Legal terminal detection happened above."""
if q.count(anchor) != 1:
    raise SystemExit(f"qstable anchor count={q.count(anchor)}")
q = q.replace(anchor, replacement, 1)

anchor = """        if qply >= MAX_QSEARCH_PLY && !in_check {
            return Some(self.leaf_evaluate(position));
        }

        let mut best = if in_check {
            -INFINITY
        } else {
            self.leaf_evaluate(position)
        };
"""
replacement = """        if qply >= MAX_QSEARCH_PLY && !in_check {
            let static_eval = self.leaf_evaluate(position);
            #[cfg(feature = \"search-trace\")]
            decision_trace::observe(position, \"qceil\", 0, ply, qply, alpha, beta, static_eval);
            return Some(static_eval);
        }

        let mut best = if in_check {
            -INFINITY
        } else {
            let static_eval = self.leaf_evaluate(position);
            #[cfg(feature = \"search-trace\")]
            decision_trace::observe(position, \"qstand\", 0, ply, qply, alpha, beta, static_eval);
            static_eval
        };
"""
if q.count(anchor) != 1:
    raise SystemExit(f"qceil/qstand anchor count={q.count(anchor)}")
q = q.replace(anchor, replacement, 1)

anchor = """        if path_len >= MAX_SEARCH_PLY {
            return Some(self.leaf_evaluate(position));
        }
"""
replacement = """        if path_len >= MAX_SEARCH_PLY {
            let static_eval = self.leaf_evaluate(position);
            #[cfg(feature = \"search-trace\")]
            decision_trace::observe(position, \"qpath\", 0, ply, qply, alpha, beta, static_eval);
            return Some(static_eval);
        }
"""
if q.count(anchor) != 1:
    raise SystemExit(f"qpath anchor count={q.count(anchor)}")
q = q.replace(anchor, replacement, 1)
qpath.write_text(q)

trace = Path("crates/chess-search/src/decision_trace.rs")
trace.write_text(r'''//! Research-only trace of static-evaluation decisions made by search.
//!
//! Compiled only under `search-trace`; normal production search has no branch, environment lookup,
//! synchronization, or I/O from this module.

use std::{
    env,
    fs::{File, OpenOptions},
    io::Write,
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
};

use chess_core::Position;

const FILE_ENV: &str = "CHESS_SEARCH_DECISION_TRACE_FILE";
const GROUP_ENV: &str = "CHESS_SEARCH_DECISION_TRACE_GROUP";
const STRIDE_ENV: &str = "CHESS_SEARCH_DECISION_TRACE_STRIDE";

static TRACE: OnceLock<Option<TraceState>> = OnceLock::new();

struct TraceState {
    group: String,
    stride: u64,
    seen: AtomicU64,
    output: Mutex<File>,
}

#[allow(clippy::too_many_arguments)]
pub(crate) fn observe(
    position: &Position,
    kind: &str,
    depth: u8,
    ply: u16,
    qply: usize,
    alpha: i32,
    beta: i32,
    score: i32,
) {
    let Some(trace) = TRACE.get_or_init(configure).as_ref() else {
        return;
    };
    let seen = trace.seen.fetch_add(1, Ordering::Relaxed);
    if seen % trace.stride != 0 {
        return;
    }
    let mut output = trace.output.lock().expect("decision trace mutex poisoned");
    writeln!(
        output,
        "{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}\t{}",
        trace.group,
        kind,
        depth,
        ply,
        qply,
        alpha,
        beta,
        score,
        position.to_fen(),
    )
    .expect("failed to append decision-trace record");
}

fn configure() -> Option<TraceState> {
    let path = match env::var(FILE_ENV) {
        Ok(path) if !path.is_empty() => path,
        Ok(_) => panic!("{FILE_ENV} must not be empty"),
        Err(env::VarError::NotPresent) => return None,
        Err(error) => panic!("failed to read {FILE_ENV}: {error}"),
    };
    let group = env::var(GROUP_ENV)
        .unwrap_or_else(|_| panic!("{GROUP_ENV} is required when {FILE_ENV} is set"));
    assert!(!group.is_empty(), "{GROUP_ENV} must not be empty");
    assert!(
        !group.chars().any(|c| matches!(c, '\t' | '\n' | '\r')),
        "{GROUP_ENV} must be one TSV field"
    );
    let stride = match env::var(STRIDE_ENV) {
        Ok(value) => value
            .parse::<u64>()
            .ok()
            .filter(|value| *value > 0)
            .unwrap_or_else(|| panic!("{STRIDE_ENV} must be a positive integer")),
        Err(env::VarError::NotPresent) => 1,
        Err(error) => panic!("failed to read {STRIDE_ENV}: {error}"),
    };
    let output = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .unwrap_or_else(|error| panic!("failed to open decision trace {path}: {error}"));
    Some(TraceState {
        group,
        stride,
        seen: AtomicU64::new(0),
        output: Mutex::new(output),
    })
}
''')

print("applied research-only RFP/qsearch decision trace")
