//! Repeat only Hyperstition accumulator inference, excluding network load and FT refresh cost.

use std::{env, hint::black_box, path::PathBuf, time::Instant};

use chess_core::Position;
use chess_eval::hyperstition::{AccumulatorState, Network};

const FENS: [&str; 6] = [
    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "2r2rk1/pp1b1ppp/2n1pn2/q2p4/3P4/P1NBPN2/1P2BPPP/2RQ1RK1 w - - 2 12",
    "4rrk1/1pp2ppp/p1n1b3/8/3P4/P1P1BN2/1P3PPP/2R2RK1 w - - 0 18",
    "8/2p5/3p2k1/1p1Pp3/pP2P3/P4K2/2P5/8 w - - 0 40",
    "r1bq1rk1/pp3ppp/2n1pn2/2bp4/8/2PB1N2/PP3PPP/R1BQR1K1 w - - 4 12",
];

fn main() -> Result<(), String> {
    let mut args = env::args_os();
    let _program = args.next();
    let path = args
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: hyperstition_tail_bench <network.nnue> [iterations]".to_owned())?;
    let iterations = args
        .next()
        .map(|value| {
            value
                .to_string_lossy()
                .parse::<usize>()
                .map_err(|error| format!("invalid iterations: {error}"))
        })
        .transpose()?
        .unwrap_or(100_000);

    let network = Network::from_file(&path)?;
    let positions = FENS
        .iter()
        .map(|fen| Position::from_fen(fen).map_err(|error| format!("invalid benchmark FEN: {error}")))
        .collect::<Result<Vec<_>, _>>()?;
    let states = positions
        .iter()
        .map(|position| {
            AccumulatorState::from_position(&network, position)
                .ok_or_else(|| "could not build benchmark accumulator".to_owned())
        })
        .collect::<Result<Vec<_>, _>>()?;

    // Warm caches and make the exact score vector visible in the report.
    let scores = states
        .iter()
        .zip(&positions)
        .map(|(state, position)| state.evaluate(&network, position))
        .collect::<Vec<_>>();
    println!("scores={scores:?}");

    let start = Instant::now();
    let mut checksum = 0_i64;
    for iteration in 0..iterations {
        for (state, position) in states.iter().zip(&positions) {
            let score = black_box(state).evaluate(black_box(&network), black_box(position));
            checksum = black_box(checksum.wrapping_add(i64::from(score) + iteration as i64));
        }
    }
    let elapsed = start.elapsed();
    let evaluations = iterations * states.len();
    let ns_per_eval = elapsed.as_nanos() as f64 / evaluations as f64;
    println!(
        "summary evaluations={evaluations} elapsed_ms={:.3} ns_per_eval={ns_per_eval:.3} checksum={checksum}",
        elapsed.as_secs_f64() * 1000.0,
    );
    Ok(())
}
