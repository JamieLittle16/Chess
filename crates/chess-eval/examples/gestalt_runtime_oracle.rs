use std::{env, path::Path};

use chess_core::Position;
use chess_eval::gestalt::Network;

fn main() {
    let mut args = env::args().skip(1);
    let network_path = args.next().expect("usage: gestalt_runtime_oracle NETWORK FEN");
    let fen = args.next().expect("usage: gestalt_runtime_oracle NETWORK FEN");
    assert!(args.next().is_none(), "usage: gestalt_runtime_oracle NETWORK FEN");

    let network = Network::from_file(Path::new(&network_path))
        .unwrap_or_else(|error| panic!("failed to load network: {error}"));
    let position = Position::from_fen(&fen).unwrap_or_else(|error| panic!("invalid FEN: {error}"));
    let score = network
        .evaluate_full(&position)
        .expect("legal FEN has both kings");
    println!("{score}");
}
