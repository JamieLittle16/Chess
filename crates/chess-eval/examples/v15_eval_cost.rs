use std::{env, hint::black_box, path::PathBuf, time::Instant};

use chess_core::Position;
use chess_eval::{
    gestalt::{AccumulatorState as GestaltState, Network as GestaltNetwork},
    perseverance::{AccumulatorState as PerseveranceState, Network as PerseveranceNetwork},
};

fn main() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let gestalt_path = args
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: v15_eval_cost <gestalt.nnue> <perseverance.bin>".to_owned())?;
    let perseverance_path = args
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: v15_eval_cost <gestalt.nnue> <perseverance.bin>".to_owned())?;
    if args.next().is_some() {
        return Err("usage: v15_eval_cost <gestalt.nnue> <perseverance.bin>".to_owned());
    }

    let gestalt = GestaltNetwork::from_file(&gestalt_path)?;
    let perseverance = PerseveranceNetwork::from_file(&perseverance_path)?;
    let positions = [
        Position::startpos(),
        Position::from_fen("r3k2r/pppq1ppp/2npbn2/3Np3/4P3/2N1B3/PPP2PPP/R2Q1RK1 b kq - 4 10")
            .map_err(|e| e.to_string())?,
        Position::from_fen("8/2p5/3p4/1P1P4/2K5/8/6k1/8 w - - 0 45")
            .map_err(|e| e.to_string())?,
    ];
    let gestalt_states = positions
        .iter()
        .map(|p| GestaltState::from_position(&gestalt, p).expect("both kings"))
        .collect::<Vec<_>>();
    let perseverance_states = positions
        .iter()
        .map(|p| PerseveranceState::from_position(&perseverance, p).expect("both kings"))
        .collect::<Vec<_>>();

    const ITERS: usize = 300_000;
    for _ in 0..10_000 {
        for (position, state) in positions.iter().zip(&gestalt_states) {
            black_box(state.evaluate(&gestalt, position.side_to_move()));
        }
        for (position, state) in positions.iter().zip(&perseverance_states) {
            black_box(state.evaluate(&perseverance, position));
        }
    }

    let start = Instant::now();
    let mut checksum = 0_i64;
    for i in 0..ITERS {
        let j = i % positions.len();
        checksum += i64::from(black_box(
            gestalt_states[j].evaluate(&gestalt, positions[j].side_to_move()),
        ));
    }
    let gestalt_elapsed = start.elapsed();

    let start = Instant::now();
    for i in 0..ITERS {
        let j = i % positions.len();
        checksum += i64::from(black_box(
            perseverance_states[j].evaluate(&perseverance, &positions[j]),
        ));
    }
    let perseverance_elapsed = start.elapsed();

    let gestalt_ns = gestalt_elapsed.as_nanos() as f64 / ITERS as f64;
    let perseverance_ns = perseverance_elapsed.as_nanos() as f64 / ITERS as f64;
    println!("gestalt_ns_per_eval={gestalt_ns:.3}");
    println!("perseverance_ns_per_eval={perseverance_ns:.3}");
    println!("perseverance_over_gestalt={:.4}", perseverance_ns / gestalt_ns);
    println!("checksum={checksum}");
    Ok(())
}
