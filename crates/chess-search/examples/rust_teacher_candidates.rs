//! Batch root-candidate oracle for Python V15 distillation/book generation.
//!
//! Usage:
//!   CHESS_GESTALT_NETWORK=/path/gestalt-b840.nnue \
//!     cargo run -p chess-search --release --example rust_teacher_candidates -- 5 4 < fens.txt
//!
//! Input is one complete FEN per line. Output is TSV:
//!   FEN<TAB>uci:score,uci:score,...
//! Scores and ranking come from the production Searcher root-analysis path, including Gestalt when
//! CHESS_GESTALT_NETWORK is configured. This binary is an offline teacher tool only; it is never
//! shipped in the Python competition submission.

use std::{env, io::{self, BufRead}};

use chess_core::{ChessMove, PieceKind, Position};
use chess_search::Searcher;

fn uci(mv: ChessMove) -> String {
    let mut out = format!("{}{}", mv.from(), mv.to());
    if let Some(piece) = mv.kind().promotion_piece() {
        out.push(match piece {
            PieceKind::Knight => 'n',
            PieceKind::Bishop => 'b',
            PieceKind::Rook => 'r',
            PieceKind::Queen => 'q',
            PieceKind::Pawn | PieceKind::King => unreachable!("only NBRQ can be promotion pieces"),
        });
    }
    out
}

fn main() -> Result<(), String> {
    let mut args = env::args().skip(1);
    let depth: u8 = args
        .next()
        .ok_or_else(|| "usage: rust_teacher_candidates DEPTH MAX_CANDIDATES".to_owned())?
        .parse()
        .map_err(|error| format!("invalid depth: {error}"))?;
    let max_candidates: usize = args
        .next()
        .ok_or_else(|| "usage: rust_teacher_candidates DEPTH MAX_CANDIDATES".to_owned())?
        .parse()
        .map_err(|error| format!("invalid max-candidates: {error}"))?;
    if args.next().is_some() || depth == 0 || max_candidates == 0 {
        return Err("usage: rust_teacher_candidates DEPTH MAX_CANDIDATES (both positive)".to_owned());
    }

    let stdin = io::stdin();
    for (index, line) in stdin.lock().lines().enumerate() {
        let fen = line.map_err(|error| format!("read stdin line {}: {error}", index + 1))?;
        let fen = fen.trim();
        if fen.is_empty() || fen.starts_with('#') {
            continue;
        }
        let mut position = Position::from_fen(fen)
            .map_err(|error| format!("invalid FEN on line {}: {error}: {fen}", index + 1))?;
        // A fresh searcher per unrelated root prevents cross-position TT/history state from turning
        // an offline dataset into a function of input ordering.
        let mut searcher = Searcher::with_tt_megabytes(64);
        let candidates = searcher.analyze_root_candidates(&mut position, depth, max_candidates);
        let encoded = candidates
            .iter()
            .map(|candidate| format!("{}:{}", uci(candidate.mv), candidate.score))
            .collect::<Vec<_>>()
            .join(",");
        println!("{fen}\t{encoded}");
    }
    Ok(())
}
