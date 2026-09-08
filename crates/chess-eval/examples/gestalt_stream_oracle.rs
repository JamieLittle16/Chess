use std::{env, io::{self, BufRead}, path::Path};

use chess_core::Position;
use chess_eval::gestalt::Network;

fn main() {
    let network_path = env::args().nth(1).expect("usage: gestalt_stream_oracle NETWORK");
    let network = Network::from_file(Path::new(&network_path))
        .unwrap_or_else(|error| panic!("failed to load network: {error}"));
    let stdin = io::stdin();
    for line in stdin.lock().lines() {
        let fen = line.expect("stdin read failed");
        if fen.trim().is_empty() { continue; }
        let position = Position::from_fen(&fen)
            .unwrap_or_else(|error| panic!("invalid FEN {fen:?}: {error}"));
        let score = network.evaluate_full(&position)
            .expect("legal FEN has both kings");
        println!("{score}");
    }
}
