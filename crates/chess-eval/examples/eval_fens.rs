use std::io::{self, BufRead};

use chess_core::Position;
use chess_eval::evaluate;

fn main() {
    for (index, line) in io::stdin().lock().lines().enumerate() {
        let line = line.unwrap_or_else(|error| panic!("failed to read line {}: {error}", index + 1));
        if line.is_empty() {
            continue;
        }
        let position = Position::from_fen(&line)
            .unwrap_or_else(|error| panic!("invalid FEN on line {}: {error}: {line}", index + 1));
        println!("{}", evaluate(&position));
    }
}
