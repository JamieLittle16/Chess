use std::io::{self, BufRead};

use chess_core::{ChessMove, PieceKind, Position, perft};

fn main() {
    for line in io::stdin().lock().lines() {
        let line = line.expect("failed to read oracle request");
        if line.is_empty() {
            continue;
        }
        println!("{}", answer(&line));
    }
}

fn answer(line: &str) -> String {
    let mut fields = line.split('\t');
    let Some(command) = fields.next() else {
        return "ERR\tempty request".to_owned();
    };

    match command {
        "moves" => {
            let Some(fen) = fields.next() else {
                return "ERR\tmoves requires FEN".to_owned();
            };
            if fields.next().is_some() {
                return "ERR\tmoves received extra fields".to_owned();
            }
            let position = match Position::from_fen(fen) {
                Ok(position) => position,
                Err(error) => return format!("ERR\tinvalid FEN: {error}"),
            };
            let mut moves: Vec<_> = position
                .legal_moves()
                .iter()
                .copied()
                .map(format_uci_move)
                .collect();
            moves.sort_unstable();
            format!("OK\t{}", moves.join(","))
        }
        "move" => {
            let Some(fen) = fields.next() else {
                return "ERR\tmove requires FEN".to_owned();
            };
            let Some(uci) = fields.next() else {
                return "ERR\tmove requires UCI move".to_owned();
            };
            if fields.next().is_some() {
                return "ERR\tmove received extra fields".to_owned();
            }
            let mut position = match Position::from_fen(fen) {
                Ok(position) => position,
                Err(error) => return format!("ERR\tinvalid FEN: {error}"),
            };
            let Some(mv) = position
                .legal_moves()
                .iter()
                .copied()
                .find(|&mv| format_uci_move(mv) == uci)
            else {
                return format!("ERR\tillegal move: {uci}");
            };
            let _undo = position.make_move(mv);
            format!("OK\t{}", position.to_fen())
        }
        "perft" => {
            let Some(fen) = fields.next() else {
                return "ERR\tperft requires FEN".to_owned();
            };
            let Some(depth) = fields.next() else {
                return "ERR\tperft requires depth".to_owned();
            };
            if fields.next().is_some() {
                return "ERR\tperft received extra fields".to_owned();
            }
            let position = match Position::from_fen(fen) {
                Ok(position) => position,
                Err(error) => return format!("ERR\tinvalid FEN: {error}"),
            };
            let depth: u32 = match depth.parse() {
                Ok(depth) => depth,
                Err(error) => return format!("ERR\tinvalid depth: {error}"),
            };
            format!("OK\t{}", perft(&position, depth))
        }
        other => format!("ERR\tunknown command: {other}"),
    }
}

fn format_uci_move(mv: ChessMove) -> String {
    let mut text = format!("{}{}", mv.from(), mv.to());
    if let Some(piece) = mv.kind().promotion_piece() {
        text.push(match piece {
            PieceKind::Knight => 'n',
            PieceKind::Bishop => 'b',
            PieceKind::Rook => 'r',
            PieceKind::Queen => 'q',
            PieceKind::Pawn | PieceKind::King => unreachable!("promotion piece is never pawn/king"),
        });
    }
    text
}

#[cfg(test)]
mod tests {
    use super::answer;

    #[test]
    fn bridge_formats_moves_applies_state_and_counts_perft() {
        let start = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";
        let moves = answer(&format!("moves\t{start}"));
        assert!(moves.starts_with("OK\t"));
        assert!(moves.contains("e2e4"));

        assert_eq!(
            answer(&format!("move\t{start}\te2e4")),
            "OK\trnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1"
        );
        assert_eq!(answer(&format!("perft\t{start}\t2")), "OK\t400");
    }
}
