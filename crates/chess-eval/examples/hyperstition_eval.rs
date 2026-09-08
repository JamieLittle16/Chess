use std::{env, path::Path, process::ExitCode};

use chess_core::Position;
use chess_eval::hyperstition::Network;

fn main() -> ExitCode {
    let mut args = env::args_os().skip(1);
    let Some(network_path) = args.next() else {
        eprintln!("usage: hyperstition_eval <decompressed-network> <fen>");
        return ExitCode::FAILURE;
    };
    let Some(fen) = args.next() else {
        eprintln!("usage: hyperstition_eval <decompressed-network> <fen>");
        return ExitCode::FAILURE;
    };
    if args.next().is_some() {
        eprintln!("fen must be passed as one quoted argument");
        return ExitCode::FAILURE;
    }

    let network = match Network::from_file(Path::new(&network_path)) {
        Ok(network) => network,
        Err(error) => {
            eprintln!("network error: {error}");
            return ExitCode::FAILURE;
        }
    };
    let fen = fen.to_string_lossy();
    let position = match Position::from_fen(&fen) {
        Ok(position) => position,
        Err(error) => {
            eprintln!("fen error: {error}");
            return ExitCode::FAILURE;
        }
    };
    let Some(score) = network.evaluate_full(&position) else {
        eprintln!("position must contain both kings");
        return ExitCode::FAILURE;
    };
    println!("{score}");
    ExitCode::SUCCESS
}
