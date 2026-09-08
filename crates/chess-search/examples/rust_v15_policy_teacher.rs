//! Export ranked Rust V15 root candidates for Python policy distillation.
//!
//! Reads one complete six-field FEN per stdin line and emits:
//!   FEN<TAB>uci:score,uci:score,...
//!
//! Set CHESS_GESTALT_NETWORK to the exact production Gestalt network before launch.

use std::env;
use std::io::{self, BufRead as _};

use chess_core::{ChessMove, PieceKind, Position};
use chess_search::Searcher;

fn uci(mv: ChessMove) -> String {
    let mut text = format!("{}{}", mv.from(), mv.to());
    if let Some(piece) = mv.kind().promotion_piece() {
        text.push(match piece {
            PieceKind::Knight => 'n',
            PieceKind::Bishop => 'b',
            PieceKind::Rook => 'r',
            PieceKind::Queen => 'q',
            PieceKind::Pawn | PieceKind::King => unreachable!("promotion target is never pawn/king"),
        });
    }
    text
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let depth: u8 = args.next().as_deref().unwrap_or("4").parse()?;
    let max_candidates: usize = args.next().as_deref().unwrap_or("6").parse()?;
    let tt_megabytes: usize = args.next().as_deref().unwrap_or("32").parse()?;
    if args.next().is_some() || depth == 0 || max_candidates == 0 {
        return Err("usage: rust_v15_policy_teacher [depth>=1] [candidates>=1] [tt_mib]".into());
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
        let candidates = searcher.analyze_root_candidates(&mut position, depth, max_candidates);
        if candidates.is_empty() {
            continue;
        }
        print!("{fen}\t");
        for (index, candidate) in candidates.iter().enumerate() {
            if index != 0 {
                print!(",");
            }
            print!("{}:{}", uci(candidate.mv), candidate.score);
        }
        println!();
    }
    Ok(())
}
