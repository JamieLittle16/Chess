use std::{io::{self, BufRead}, process};

use chess_core::Position;
use chess_eval::evaluate;

fn main() {
    let stdin = io::stdin();
    for (line_no, line) in stdin.lock().lines().enumerate() {
        let fen = line.unwrap_or_else(|error| {
            eprintln!("failed to read input line {}: {error}", line_no + 1);
            process::exit(2);
        });
        if fen.is_empty() {
            eprintln!("empty FEN at input line {}", line_no + 1);
            process::exit(2);
        }
        let position = Position::from_fen(&fen).unwrap_or_else(|error| {
            eprintln!("invalid FEN at input line {}: {error}", line_no + 1);
            process::exit(2);
        });
        println!("{}", evaluate(&position));
    }
}
