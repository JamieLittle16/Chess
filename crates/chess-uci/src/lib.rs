//! Minimal synchronous UCI protocol adapter for the reference engine.
//!
//! Protocol parsing is intentionally outside chess correctness. Coordinate moves are resolved
//! against the current legal move list, so this crate never re-implements move semantics.

use chess_core::{ChessMove, PieceKind, Position, Square};
use chess_engine::{Engine, MATE_SCORE, SearchResult};

/// Output produced by one input command.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct UciResponse {
    lines: Vec<String>,
    quit: bool,
}

impl UciResponse {
    #[must_use]
    pub fn lines(&self) -> &[String] {
        &self.lines
    }

    #[must_use]
    pub const fn should_quit(&self) -> bool {
        self.quit
    }
}

/// Stateful synchronous UCI session.
pub struct UciSession {
    engine: Engine,
}

impl UciSession {
    #[must_use]
    pub fn new() -> Self {
        Self {
            engine: Engine::new(),
        }
    }

    #[must_use]
    pub const fn engine(&self) -> &Engine {
        &self.engine
    }

    /// Handle one complete UCI input line.
    #[must_use]
    pub fn handle_line(&mut self, line: &str) -> UciResponse {
        let tokens: Vec<_> = line.split_whitespace().collect();
        let Some(command) = tokens.first().copied() else {
            return response(Vec::new(), false);
        };

        match command {
            "uci" => response(
                vec![
                    "id name Chess 0.1.0".to_owned(),
                    "id author Jamie Little".to_owned(),
                    "uciok".to_owned(),
                ],
                false,
            ),
            "isready" => response(vec!["readyok".to_owned()], false),
            "ucinewgame" => {
                self.engine.new_game();
                response(Vec::new(), false)
            }
            "position" => match parse_position(&tokens) {
                Ok(position) => {
                    self.engine.set_position(position);
                    response(Vec::new(), false)
                }
                Err(message) => response(vec![format!("info string {message}")], false),
            },
            "go" => self.handle_go(&tokens),
            "stop" => response(Vec::new(), false),
            "quit" => response(Vec::new(), true),
            _ => response(Vec::new(), false),
        }
    }

    fn handle_go(&mut self, tokens: &[&str]) -> UciResponse {
        let depth = tokens
            .windows(2)
            .find(|pair| pair[0] == "depth")
            .and_then(|pair| pair[1].parse::<u8>().ok())
            .filter(|depth| *depth > 0);

        let Some(depth) = depth else {
            return response(
                vec![
                    "info string only 'go depth N' is supported currently".to_owned(),
                    "bestmove 0000".to_owned(),
                ],
                false,
            );
        };

        let result = self.engine.search_depth(depth);
        response(search_lines(result), false)
    }
}

impl Default for UciSession {
    fn default() -> Self {
        Self::new()
    }
}

fn response(lines: Vec<String>, quit: bool) -> UciResponse {
    UciResponse { lines, quit }
}

fn parse_position(tokens: &[&str]) -> Result<Position, &'static str> {
    let Some(kind) = tokens.get(1).copied() else {
        return Err("position requires 'startpos' or 'fen'");
    };

    let (mut position, mut index) = match kind {
        "startpos" => (Position::startpos(), 2),
        "fen" => {
            if tokens.len() < 8 {
                return Err("position fen requires all six FEN fields");
            }
            let fen = tokens[2..8].join(" ");
            let position = Position::from_fen(&fen).map_err(|_| "invalid FEN")?;
            (position, 8)
        }
        _ => return Err("position requires 'startpos' or 'fen'"),
    };

    if index == tokens.len() {
        return Ok(position);
    }
    if tokens.get(index) != Some(&"moves") {
        return Err("unexpected token after base position");
    }
    index += 1;

    while let Some(text) = tokens.get(index) {
        let mv = resolve_uci_move(&position, text).ok_or("illegal or malformed UCI move")?;
        let _undo = position.make_move(mv);
        index += 1;
    }
    Ok(position)
}

/// Resolve UCI coordinate notation against the legal moves of `position`.
#[must_use]
pub fn resolve_uci_move(position: &Position, text: &str) -> Option<ChessMove> {
    let bytes = text.as_bytes();
    if bytes.len() != 4 && bytes.len() != 5 {
        return None;
    }

    let from = parse_square(bytes[0], bytes[1])?;
    let to = parse_square(bytes[2], bytes[3])?;
    let promotion = if bytes.len() == 5 {
        Some(match bytes[4] {
            b'n' => PieceKind::Knight,
            b'b' => PieceKind::Bishop,
            b'r' => PieceKind::Rook,
            b'q' => PieceKind::Queen,
            _ => return None,
        })
    } else {
        None
    };

    position
        .legal_moves()
        .as_slice()
        .iter()
        .copied()
        .find(|mv| {
            mv.from() == from
                && mv.to() == to
                && match promotion {
                    Some(kind) => mv.kind().promotion_piece() == Some(kind),
                    None => !mv.kind().is_promotion(),
                }
        })
}

/// Encode one internal legal move as UCI coordinate notation.
#[must_use]
pub fn format_uci_move(mv: ChessMove) -> String {
    let mut text = format!("{}{}", mv.from(), mv.to());
    if let Some(piece) = mv.kind().promotion_piece() {
        text.push(match piece {
            PieceKind::Knight => 'n',
            PieceKind::Bishop => 'b',
            PieceKind::Rook => 'r',
            PieceKind::Queen => 'q',
            PieceKind::Pawn | PieceKind::King => unreachable!("promotion target is N/B/R/Q"),
        });
    }
    text
}

fn parse_square(file: u8, rank: u8) -> Option<Square> {
    if !(b'a'..=b'h').contains(&file) || !(b'1'..=b'8').contains(&rank) {
        return None;
    }
    Square::from_file_rank(file - b'a', rank - b'1')
}

fn search_lines(result: SearchResult) -> Vec<String> {
    let score = format_score(result.score);
    let bestmove = result
        .best_move
        .map_or_else(|| "0000".to_owned(), format_uci_move);
    vec![
        format!(
            "info depth {} score {} nodes {}",
            result.depth, score, result.nodes
        ),
        format!("bestmove {bestmove}"),
    ]
}

fn format_score(score: i32) -> String {
    let mate_threshold = MATE_SCORE - 1_000;
    if score.abs() >= mate_threshold {
        let plies = MATE_SCORE - score.abs();
        let moves = (plies + 1) / 2;
        let signed_moves = if score < 0 { -moves } else { moves };
        format!("mate {signed_moves}")
    } else {
        format!("cp {score}")
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, PieceKind, Position};

    use super::{UciSession, format_uci_move, resolve_uci_move};

    #[test]
    fn handshake_and_readiness_are_standard() {
        let mut session = UciSession::new();
        let uci = session.handle_line("uci");
        assert_eq!(
            uci.lines(),
            [
                "id name Chess 0.1.0",
                "id author Jamie Little",
                "uciok"
            ]
        );
        assert_eq!(session.handle_line("isready").lines(), ["readyok"]);
    }

    #[test]
    fn position_move_sequence_is_resolved_through_legal_chess() {
        let mut session = UciSession::new();
        assert!(
            session
                .handle_line("position startpos moves e2e4 e7e5")
                .lines()
                .is_empty()
        );
        assert_eq!(session.engine().position().side_to_move(), Color::White);
    }

    #[test]
    fn invalid_position_command_is_transactional() {
        let mut session = UciSession::new();
        let root = session.engine().position().clone();
        let response = session.handle_line("position startpos moves e2e5");
        assert_eq!(response.lines().len(), 1);
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn promotions_round_trip_through_uci_text() {
        let position = Position::from_fen("7k/P7/8/8/8/8/8/K7 w - - 0 1").expect("valid FEN");
        let mv = resolve_uci_move(&position, "a7a8q").expect("queen promotion is legal");
        assert_eq!(mv.kind().promotion_piece(), Some(PieceKind::Queen));
        assert_eq!(format_uci_move(mv), "a7a8q");
    }

    #[test]
    fn fixed_depth_go_returns_a_legal_bestmove() {
        let mut session = UciSession::new();
        let root = session.engine().position().clone();
        let response = session.handle_line("go depth 1");
        assert_eq!(response.lines().len(), 2);
        assert!(response.lines()[0].starts_with("info depth 1 score "));
        let best = response.lines()[1]
            .strip_prefix("bestmove ")
            .expect("bestmove line");
        assert!(resolve_uci_move(&root, best).is_some());
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn quit_sets_session_flag() {
        let mut session = UciSession::new();
        assert!(session.handle_line("quit").should_quit());
    }
}
