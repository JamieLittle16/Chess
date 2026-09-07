use std::{env, fs, hint::black_box, process, time::Instant};

use chess_core::{ChessMove, Position};
use chess_eval::nnue::network::{Network, accumulator::AccumulatorState};

const DEFAULT_REPETITIONS: usize = 160;
const LINE_PLIES: usize = 96;

fn main() {
    let mut args = env::args().skip(1);
    let path = args.next().unwrap_or_else(|| {
        eprintln!("usage: nnue_cost <network.nnue> [repetitions]");
        process::exit(2);
    });
    let repetitions = args
        .next()
        .map(|value| {
            value
                .parse::<usize>()
                .expect("repetitions must be a positive integer")
        })
        .unwrap_or(DEFAULT_REPETITIONS);
    assert!(repetitions > 0, "repetitions must be positive");

    let bytes = fs::read(&path).unwrap_or_else(|error| {
        eprintln!("failed to read {path}: {error}");
        process::exit(2);
    });
    let network = Network::from_bytes(&bytes).unwrap_or_else(|error| {
        eprintln!("failed to load {path}: {error}");
        process::exit(2);
    });

    let line = deterministic_line();
    assert!(!line.is_empty(), "cost line unexpectedly empty");
    let positions = materialize_positions(&line);

    let (full_elapsed, full_checksum) = time_full_refresh(&network, &positions, repetitions);
    let (position_elapsed, position_checksum) = time_position_round_trip(&line, repetitions);
    let (incremental_elapsed, incremental_checksum) =
        time_incremental_round_trip(&network, &line, repetitions);

    let forward_ops = repetitions * line.len();
    let full_ns = nanos_per(full_elapsed, repetitions * positions.len());
    let position_ns = nanos_per(position_elapsed, forward_ops);
    let incremental_ns = nanos_per(incremental_elapsed, forward_ops);
    let nnue_overhead_ns = incremental_ns.saturating_sub(position_ns);
    let checksum = full_checksum ^ position_checksum ^ incremental_checksum;

    println!(
        "{{\"hidden\":{},\"line_plies\":{},\"repetitions\":{},\"full_refresh_ns_per_eval\":{},\"position_round_trip_ns_per_forward\":{},\"incremental_round_trip_eval_ns_per_forward\":{},\"incremental_nnue_overhead_estimate_ns\":{},\"checksum\":{}}}",
        network.hidden(),
        line.len(),
        repetitions,
        full_ns,
        position_ns,
        incremental_ns,
        nnue_overhead_ns,
        checksum
    );
}

fn deterministic_line() -> Vec<ChessMove> {
    let mut position = Position::startpos();
    let mut line = Vec::with_capacity(LINE_PLIES);
    for ply in 0..LINE_PLIES {
        let moves = position.legal_moves();
        if moves.is_empty() {
            break;
        }
        let mv = moves[(ply.wrapping_mul(37).wrapping_add(13)) % moves.len()];
        let _undo = position.make_move(mv);
        line.push(mv);
    }
    line
}

fn materialize_positions(line: &[ChessMove]) -> Vec<Position> {
    let mut position = Position::startpos();
    let mut positions = Vec::with_capacity(line.len());
    for &mv in line {
        let _undo = position.make_move(mv);
        positions.push(position.clone());
    }
    positions
}

fn time_full_refresh(
    network: &Network,
    positions: &[Position],
    repetitions: usize,
) -> (std::time::Duration, u64) {
    let mut checksum = 0_u64;
    let start = Instant::now();
    for _ in 0..repetitions {
        for position in positions {
            let score = network
                .evaluate_full(black_box(position))
                .expect("legal benchmark position");
            checksum = checksum.rotate_left(7) ^ score as u64;
        }
    }
    (start.elapsed(), black_box(checksum))
}

fn time_position_round_trip(line: &[ChessMove], repetitions: usize) -> (std::time::Duration, u64) {
    let mut position = Position::startpos();
    let mut history = Vec::with_capacity(line.len());
    let mut checksum = 0_u64;
    let start = Instant::now();
    for _ in 0..repetitions {
        for &mv in line {
            let undo = position.make_move(mv);
            checksum ^= position.zobrist_key().raw().rotate_left(11);
            history.push((mv, undo));
        }
        while let Some((mv, undo)) = history.pop() {
            position.unmake_move(mv, undo);
        }
    }
    let elapsed = start.elapsed();
    assert_eq!(position, Position::startpos());
    (elapsed, black_box(checksum))
}

fn time_incremental_round_trip(
    network: &Network,
    line: &[ChessMove],
    repetitions: usize,
) -> (std::time::Duration, u64) {
    let mut position = Position::startpos();
    let mut accumulator =
        AccumulatorState::from_position(network, &position).expect("legal benchmark root");
    let root_accumulator = accumulator.clone();
    let mut history = Vec::with_capacity(line.len());
    let mut checksum = 0_u64;

    let start = Instant::now();
    for _ in 0..repetitions {
        for &mv in line {
            let prepared = AccumulatorState::prepare_move(&position, mv).expect("legal update");
            let undo = position.make_move(mv);
            accumulator
                .apply_prepared(network, &position, prepared)
                .expect("legal child accumulator");
            let score = accumulator.evaluate(network, position.side_to_move());
            checksum = checksum.rotate_left(5) ^ score as u64;
            history.push((mv, undo, prepared));
        }
        while let Some((mv, undo, prepared)) = history.pop() {
            position.unmake_move(mv, undo);
            accumulator
                .restore_after_unmake(network, &position, prepared)
                .expect("legal restored accumulator");
        }
    }
    let elapsed = start.elapsed();
    assert_eq!(position, Position::startpos());
    assert_eq!(accumulator, root_accumulator);
    (elapsed, black_box(checksum))
}

fn nanos_per(elapsed: std::time::Duration, operations: usize) -> u128 {
    elapsed.as_nanos() / operations as u128
}
