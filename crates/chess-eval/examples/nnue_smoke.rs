use std::{env, fs, process};

use chess_core::Position;
use chess_eval::nnue::network::Network;

fn main() {
    let path = env::args().nth(1).unwrap_or_else(|| {
        eprintln!("usage: nnue_smoke <network.nnue>");
        process::exit(2);
    });
    let bytes = fs::read(&path).unwrap_or_else(|error| {
        eprintln!("failed to read {path}: {error}");
        process::exit(2);
    });
    let network = Network::from_bytes(&bytes).unwrap_or_else(|error| {
        eprintln!("failed to load {path}: {error}");
        process::exit(2);
    });
    let score = network
        .evaluate_full(&Position::startpos())
        .expect("start position has both kings");
    println!("hidden={} startpos_score={score}", network.hidden());
}
