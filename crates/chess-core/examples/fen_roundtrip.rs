use std::io::{self, BufRead};

use chess_core::Position;

fn main() {
    for (index, line) in io::stdin().lock().lines().enumerate() {
        let line =
            line.unwrap_or_else(|error| panic!("failed to read line {}: {error}", index + 1));
        if line.is_empty() {
            continue;
        }
        let fen = line.split_once('\t').map_or(line.as_str(), |(_, fen)| fen);
        let position = Position::from_fen(fen).unwrap_or_else(|error| {
            panic!("invalid corpus FEN on line {}: {error}: {fen}", index + 1)
        });
        assert_eq!(
            position.to_fen(),
            fen,
            "non-canonical corpus FEN on line {}",
            index + 1
        );
    }
}
