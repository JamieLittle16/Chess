//! Stream exact production Gestalt static scores for evaluator distillation.
use std::env;
use std::io::{self, BufRead as _};
use std::path::Path;

use chess_core::Position;
use chess_eval::gestalt::Network;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let path = env::var("CHESS_GESTALT_NETWORK")
        .map_err(|_| "CHESS_GESTALT_NETWORK must point to gestalt-b840.nnue")?;
    let network = Network::from_file(Path::new(&path))?;
    let stdin = io::stdin();
    for (line_number, line) in stdin.lock().lines().enumerate() {
        let fen = line?;
        let fen = fen.trim();
        if fen.is_empty() || fen.starts_with('#') {
            continue;
        }
        let position = Position::from_fen(fen)
            .map_err(|error| format!("line {} invalid FEN: {error}", line_number + 1))?;
        if let Some(score) = network.evaluate_full(&position) {
            println!("{fen}\t{score}");
        }
    }
    Ok(())
}
