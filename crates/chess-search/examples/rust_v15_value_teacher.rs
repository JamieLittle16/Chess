//! Export exact Rust V15 backed-up root values for evaluator distillation.
//!
//! Reads one complete six-field FEN per stdin line and emits:
//!   FEN<TAB>score
//!
//! The score is from the side-to-move perspective. Set CHESS_GESTALT_NETWORK to the exact
//! production Gestalt network before launch.

use std::env;
use std::io::{self, BufRead as _};

use chess_core::Position;
use chess_search::Searcher;

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let depth: u8 = args.next().as_deref().unwrap_or("3").parse()?;
    let tt_megabytes: usize = args.next().as_deref().unwrap_or("32").parse()?;
    if args.next().is_some() || depth == 0 {
        return Err("usage: rust_v15_value_teacher [depth>=1] [tt_mib]".into());
    }

    let stdin = io::stdin();
    let mut searcher = Searcher::with_tt_megabytes(tt_megabytes);
    for (line_number, line) in stdin.lock().lines().enumerate() {
        let fen = line?;
        let fen = fen.trim();
        if fen.is_empty() || fen.starts_with('#') {
            continue;
        }
        let mut position = Position::from_fen(fen)
            .map_err(|error| format!("line {} invalid FEN: {error}", line_number + 1))?;
        let candidates = searcher.analyze_root_candidates(&mut position, depth, 1);
        if let Some(candidate) = candidates.first() {
            println!("{fen}\t{}", candidate.score);
        }
    }
    Ok(())
}
