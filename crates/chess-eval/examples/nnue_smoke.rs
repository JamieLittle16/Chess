use std::{env, fs, process};

use chess_core::{Color, Position};
use chess_eval::nnue::{FeatureIndex, active_features, network::Network};

const SMOKE_FEN: &str = "2k5/5p2/8/3N4/6b1/1P6/8/4K3 w - - 0 1";

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

    let position = Position::from_fen(SMOKE_FEN).expect("fixed NNUE smoke FEN is valid");
    let score = network
        .evaluate_full(&position)
        .expect("smoke position has both kings");
    let white = active_features(&position, Color::White).expect("white feature frame exists");
    let black = active_features(&position, Color::Black).expect("black feature frame exists");

    println!("hidden={} smoke_score={score}", network.hidden());
    print_features("white_features", white.as_slice());
    print_features("black_features", black.as_slice());
}

fn print_features(label: &str, features: &[FeatureIndex]) {
    print!("{label}=");
    for (index, feature) in features.iter().enumerate() {
        if index != 0 {
            print!(",");
        }
        print!("{}", feature.raw());
    }
    println!();
}
