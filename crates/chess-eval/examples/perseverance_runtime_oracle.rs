//! Score one FEN with the production-shaped V15 perseverance runtime.

use std::{env, path::PathBuf};

use chess_core::Position;
use chess_eval::perseverance::Network;

fn main() -> Result<(), String> {
    let mut args = env::args_os().skip(1);
    let network = args
        .next()
        .map(PathBuf::from)
        .ok_or_else(|| "usage: perseverance_runtime_oracle <perseverance.bin> '<FEN>'".to_owned())?;
    let fen = args
        .next()
        .ok_or_else(|| "usage: perseverance_runtime_oracle <perseverance.bin> '<FEN>'".to_owned())?;
    if args.next().is_some() {
        return Err("FEN must be passed as one quoted argument".to_owned());
    }
    let fen = fen
        .into_string()
        .map_err(|_| "FEN is not valid UTF-8".to_owned())?;
    let position = Position::from_fen(&fen).map_err(|error| format!("invalid FEN: {error}"))?;
    let network = Network::from_file(&network)?;
    let score = network
        .evaluate_full(&position)
        .ok_or_else(|| "position must contain both kings".to_owned())?;
    println!("{score}");
    Ok(())
}
