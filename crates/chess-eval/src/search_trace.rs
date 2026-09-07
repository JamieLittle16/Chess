//! Offline static-evaluation trace sink used to build search-distribution training corpora.
//!
//! This module is compiled only with the `search-trace` feature. Normal engine builds contain no
//! observer branch, environment lookup, synchronization or file I/O. Qualification jobs run one
//! traced engine process per canonical opening root and supply that root's split group explicitly.

use std::{
    env,
    fs::{File, OpenOptions},
    io::{BufWriter, Write},
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
};

use chess_core::Position;

const TRACE_FILE_ENV: &str = "CHESS_SEARCH_TRACE_FILE";
const TRACE_GROUP_ENV: &str = "CHESS_SEARCH_TRACE_GROUP";
const TRACE_STRIDE_ENV: &str = "CHESS_SEARCH_TRACE_STRIDE";

static TRACE: OnceLock<Option<TraceState>> = OnceLock::new();

struct TraceState {
    group: String,
    stride: u64,
    seen: AtomicU64,
    output: Mutex<BufWriter<File>>,
}

pub(crate) fn observe(position: &Position) {
    let Some(trace) = TRACE.get_or_init(configure).as_ref() else {
        return;
    };
    let seen = trace.seen.fetch_add(1, Ordering::Relaxed);
    if seen % trace.stride != 0 {
        return;
    }

    let mut output = trace.output.lock().expect("search trace output mutex poisoned");
    writeln!(output, "{}\t{}", trace.group, position.to_fen())
        .expect("failed to append search-trace record");
}

fn configure() -> Option<TraceState> {
    let path = match env::var(TRACE_FILE_ENV) {
        Ok(path) if !path.is_empty() => path,
        Ok(_) => panic!("{TRACE_FILE_ENV} must not be empty when configured"),
        Err(env::VarError::NotPresent) => return None,
        Err(error) => panic!("failed to read {TRACE_FILE_ENV}: {error}"),
    };
    let group = env::var(TRACE_GROUP_ENV)
        .unwrap_or_else(|_| panic!("{TRACE_GROUP_ENV} is required when {TRACE_FILE_ENV} is set"));
    assert!(!group.is_empty(), "{TRACE_GROUP_ENV} must not be empty");
    assert!(
        !group
            .chars()
            .any(|character| matches!(character, '\t' | '\n' | '\r')),
        "{TRACE_GROUP_ENV} must be one TSV field"
    );

    let stride = match env::var(TRACE_STRIDE_ENV) {
        Ok(value) => value
            .parse::<u64>()
            .ok()
            .filter(|stride| *stride > 0)
            .unwrap_or_else(|| panic!("{TRACE_STRIDE_ENV} must be a positive integer")),
        Err(env::VarError::NotPresent) => 1,
        Err(error) => panic!("failed to read {TRACE_STRIDE_ENV}: {error}"),
    };
    let file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(&path)
        .unwrap_or_else(|error| panic!("failed to open search trace {path}: {error}"));

    Some(TraceState {
        group,
        stride,
        seen: AtomicU64::new(0),
        output: Mutex::new(BufWriter::new(file)),
    })
}
