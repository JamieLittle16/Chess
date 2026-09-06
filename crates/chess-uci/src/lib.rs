//! Minimal UCI protocol adapter for the reference engine.
//!
//! Protocol parsing is intentionally outside chess correctness. Coordinate moves are resolved
//! against the current legal move list, so this crate never re-implements move semantics.

use std::time::Duration;

use chess_core::{ChessMove, Color, PieceKind, Position, Square};
use chess_engine::{
    ClockState, DEFAULT_HASH_MB, Engine, MATE_SCORE, MAX_HASH_MB, MIN_HASH_MB, SearchLimits,
    SearchResult, StopToken,
};

/// Safety cap used when a dynamically limited search has no explicit depth constraint.
const DEFAULT_LIMIT_DEPTH: u8 = 64;

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

/// Stateful UCI session.
///
/// The normal constructor keeps pure fixed-depth search on the zero-overhead reference path. The
/// interruptible constructor is intended for the executable's long-lived search worker and routes
/// every search through a shared `StopToken`, allowing another thread to request cancellation.
pub struct UciSession {
    engine: Engine,
    stop: StopToken,
    interruptible: bool,
}

impl UciSession {
    #[must_use]
    pub fn new() -> Self {
        Self {
            engine: Engine::new(),
            stop: StopToken::new(),
            interruptible: false,
        }
    }

    /// Construct a session whose searches can be stopped through `stop_token()`.
    #[must_use]
    pub fn new_interruptible() -> Self {
        Self {
            engine: Engine::new(),
            stop: StopToken::new(),
            interruptible: true,
        }
    }

    #[must_use]
    pub const fn engine(&self) -> &Engine {
        &self.engine
    }

    /// Clone the cooperative cancellation signal used by an interruptible session.
    ///
    /// Callers should reset the token immediately before admitting a new `go` command, then retain
    /// a clone on the protocol/input thread so `stop` does not need access to mutable engine state.
    #[must_use]
    pub fn stop_token(&self) -> StopToken {
        self.stop.clone()
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
                    format!(
                        "option name Hash type spin default {DEFAULT_HASH_MB} min {MIN_HASH_MB} max {MAX_HASH_MB}"
                    ),
                    "uciok".to_owned(),
                ],
                false,
            ),
            "isready" => response(vec!["readyok".to_owned()], false),
            "setoption" => self.handle_setoption(&tokens),
            "ucinewgame" => {
                self.engine.new_game();
                response(Vec::new(), false)
            }
            "position" => match parse_position(&tokens) {
                Ok(parsed) => {
                    self.engine
                        .set_position_with_prior_history(parsed.position, parsed.prior_history);
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

    fn handle_setoption(&mut self, tokens: &[&str]) -> UciResponse {
        match parse_hash_option(tokens) {
            Ok(hash_mb) => {
                self.engine.set_hash_mb(hash_mb);
                response(Vec::new(), false)
            }
            Err(message) => response(vec![format!("info string {message}")], false),
        }
    }

    fn handle_go(&mut self, tokens: &[&str]) -> UciResponse {
        let limits = match parse_go_request(tokens)
            .and_then(|request| request.into_limits(self.engine.position().side_to_move()))
        {
            Ok(limits) => limits,
            Err(message) => {
                return response(
                    vec![format!("info string {message}"), "bestmove 0000".to_owned()],
                    false,
                );
            }
        };

        // Synchronous fixed-depth callers keep the ordinary zero-overhead path. An interruptible
        // worker must route every search through cooperative control so `stop` can cancel depth-only
        // searches too. Node/time limits necessarily use the controlled path in both modes.
        let controlled =
            self.interruptible || limits.max_nodes.is_some() || limits.movetime.is_some();
        let result = if controlled {
            self.engine.search_with_limits(limits, &self.stop).result
        } else {
            self.engine.search_depth(limits.max_depth)
        };
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

fn parse_hash_option(tokens: &[&str]) -> Result<usize, &'static str> {
    if tokens.get(1) != Some(&"name")
        || tokens.get(2) != Some(&"Hash")
        || tokens.get(3) != Some(&"value")
        || tokens.len() != 5
    {
        return Err("supported setoption syntax is: setoption name Hash value <MiB>");
    }

    let value = tokens[4]
        .parse::<usize>()
        .map_err(|_| "Hash requires an integer MiB value")?;
    if !(MIN_HASH_MB..=MAX_HASH_MB).contains(&value) {
        return Err("Hash value is outside the advertised range");
    }
    Ok(value)
}

#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
struct GoRequest {
    depth: Option<u8>,
    nodes: Option<u64>,
    movetime: Option<Duration>,
    wtime: Option<Duration>,
    btime: Option<Duration>,
    winc: Option<Duration>,
    binc: Option<Duration>,
    moves_to_go: Option<u32>,
}

impl GoRequest {
    fn into_limits(self, side_to_move: Color) -> Result<SearchLimits, &'static str> {
        let has_clock_fields = self.wtime.is_some()
            || self.btime.is_some()
            || self.winc.is_some()
            || self.binc.is_some()
            || self.moves_to_go.is_some();

        let clock_budget = if has_clock_fields {
            let (remaining, increment) = match side_to_move {
                Color::White => (
                    self.wtime
                        .ok_or("go clock is missing wtime for White to move")?,
                    self.winc.unwrap_or(Duration::ZERO),
                ),
                Color::Black => (
                    self.btime
                        .ok_or("go clock is missing btime for Black to move")?,
                    self.binc.unwrap_or(Duration::ZERO),
                ),
            };
            Some(ClockState::new(remaining, increment, self.moves_to_go).allocated_movetime())
        } else {
            None
        };

        let movetime = match (self.movetime, clock_budget) {
            (Some(fixed), Some(clock)) => Some(fixed.min(clock)),
            (Some(fixed), None) => Some(fixed),
            (None, Some(clock)) => Some(clock),
            (None, None) => None,
        };

        if self.depth.is_none() && self.nodes.is_none() && movetime.is_none() {
            return Err("go requires depth, nodes, movetime, or a game clock");
        }

        Ok(SearchLimits {
            max_depth: self.depth.unwrap_or(DEFAULT_LIMIT_DEPTH),
            max_nodes: self.nodes,
            movetime,
        })
    }
}

fn parse_go_request(tokens: &[&str]) -> Result<GoRequest, &'static str> {
    let mut request = GoRequest::default();
    let mut index = 1;

    while index < tokens.len() {
        let key = tokens[index];
        let Some(value) = tokens.get(index + 1).copied() else {
            return Err("go limit requires a value");
        };

        match key {
            "depth" => {
                request.depth = Some(
                    value
                        .parse::<u8>()
                        .ok()
                        .filter(|value| *value > 0)
                        .ok_or("go depth requires a positive integer")?,
                );
            }
            "nodes" => {
                request.nodes = Some(
                    value
                        .parse::<u64>()
                        .ok()
                        .filter(|value| *value > 0)
                        .ok_or("go nodes requires a positive integer")?,
                );
            }
            "movetime" => {
                request.movetime = Some(parse_millis(
                    value,
                    "go movetime requires integer milliseconds",
                )?);
            }
            "wtime" => {
                request.wtime = Some(parse_millis(
                    value,
                    "go wtime requires integer milliseconds",
                )?);
            }
            "btime" => {
                request.btime = Some(parse_millis(
                    value,
                    "go btime requires integer milliseconds",
                )?);
            }
            "winc" => {
                request.winc = Some(parse_millis(
                    value,
                    "go winc requires integer milliseconds",
                )?);
            }
            "binc" => {
                request.binc = Some(parse_millis(
                    value,
                    "go binc requires integer milliseconds",
                )?);
            }
            "movestogo" => {
                request.moves_to_go = Some(
                    value
                        .parse::<u32>()
                        .ok()
                        .filter(|value| *value > 0)
                        .ok_or("go movestogo requires a positive integer")?,
                );
            }
            _ => {
                return Err(
                    "unsupported go limit; use depth, nodes, movetime, wtime/btime, increments, or movestogo",
                );
            }
        }
        index += 2;
    }

    Ok(request)
}

fn parse_millis(value: &str, error: &'static str) -> Result<Duration, &'static str> {
    value
        .parse::<u64>()
        .map(Duration::from_millis)
        .map_err(|_| error)
}

struct ParsedPosition {
    position: Position,
    prior_history: Vec<u64>,
}

fn parse_position(tokens: &[&str]) -> Result<ParsedPosition, &'static str> {
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

    let mut prior_history = Vec::new();
    if index == tokens.len() {
        return Ok(ParsedPosition {
            position,
            prior_history,
        });
    }
    if tokens.get(index) != Some(&"moves") {
        return Err("unexpected token after base position");
    }
    index += 1;

    while let Some(text) = tokens.get(index) {
        let mv = resolve_uci_move(&position, text).ok_or("illegal or malformed UCI move")?;
        prior_history.push(position.repetition_key().raw());
        let _undo = position.make_move(mv);
        index += 1;
    }
    Ok(ParsedPosition {
        position,
        prior_history,
    })
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
    use std::time::Duration;

    use chess_core::{Color, PieceKind, Position};
    use chess_engine::{DEFAULT_HASH_MB, MAX_HASH_MB};

    use super::{
        DEFAULT_LIMIT_DEPTH, UciSession, format_uci_move, parse_go_request, resolve_uci_move,
    };

    #[test]
    fn handshake_and_readiness_are_standard() {
        let mut session = UciSession::new();
        let uci = session.handle_line("uci");
        assert_eq!(
            uci.lines(),
            [
                "id name Chess 0.1.0",
                "id author Jamie Little",
                "option name Hash type spin default 32 min 1 max 1024",
                "uciok",
            ]
        );
        assert_eq!(session.handle_line("isready").lines(), ["readyok"]);
    }

    #[test]
    fn hash_option_resizes_search_memory_without_losing_configuration_on_new_game() {
        let mut session = UciSession::new();
        assert_eq!(session.engine().hash_mb(), DEFAULT_HASH_MB);
        assert!(
            session
                .handle_line("setoption name Hash value 64")
                .lines()
                .is_empty()
        );
        assert_eq!(session.engine().hash_mb(), 64);

        let invalid = session.handle_line("setoption name Hash value 0");
        assert_eq!(invalid.lines().len(), 1);
        assert_eq!(session.engine().hash_mb(), 64);

        let too_large = format!("setoption name Hash value {}", MAX_HASH_MB + 1);
        assert_eq!(session.handle_line(&too_large).lines().len(), 1);
        assert_eq!(session.engine().hash_mb(), 64);

        let _ = session.handle_line("ucinewgame");
        assert_eq!(session.engine().hash_mb(), 64);
    }

    #[test]
    fn position_move_sequence_is_resolved_through_legal_chess_and_history() {
        let mut session = UciSession::new();
        assert!(
            session
                .handle_line("position startpos moves e2e4 e7e5")
                .lines()
                .is_empty()
        );
        assert_eq!(session.engine().position().side_to_move(), Color::White);
        assert_eq!(session.engine().repetition_history().len(), 3);
        assert_eq!(
            session.engine().repetition_history().last().copied(),
            Some(session.engine().position().repetition_key().raw())
        );
    }

    #[test]
    fn invalid_position_command_is_transactional_for_board_and_history() {
        let mut session = UciSession::new();
        let root = session.engine().position().clone();
        let history = session.engine().repetition_history().to_vec();
        let response = session.handle_line("position startpos moves e2e4 e7e5 e4e6");
        assert_eq!(response.lines().len(), 1);
        assert_eq!(session.engine().position(), &root);
        assert_eq!(session.engine().repetition_history(), history);
    }

    #[test]
    fn uci_move_sequence_preserves_threefold_context_for_search() {
        let mut session = UciSession::new();
        let command = concat!(
            "position fen 7k/8/8/8/8/8/6Q1/K7 w - - 0 1 moves ",
            "a1a2 h8h7 a2a1 h7h8 a1a2 h8h7 a2a1 h7h8"
        );
        assert!(session.handle_line(command).lines().is_empty());

        let key = session.engine().position().repetition_key().raw();
        assert_eq!(
            session
                .engine()
                .repetition_history()
                .iter()
                .filter(|&&candidate| candidate == key)
                .count(),
            3
        );
        let response = session.handle_line("go depth 1");
        assert!(response.lines()[0].contains("score cp 0"));
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
    fn node_limited_go_returns_a_legal_bestmove_and_restores_root() {
        let mut session = UciSession::new();
        let root = session.engine().position().clone();
        let response = session.handle_line("go nodes 20");
        assert_eq!(response.lines().len(), 2);
        assert!(response.lines()[0].starts_with("info depth 0 score "));
        let best = response.lines()[1]
            .strip_prefix("bestmove ")
            .expect("bestmove line");
        assert!(resolve_uci_move(&root, best).is_some());
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn zero_movetime_returns_an_immediate_legal_fallback() {
        let mut session = UciSession::new();
        let root = session.engine().position().clone();
        let response = session.handle_line("go movetime 0");
        assert_eq!(response.lines().len(), 2);
        assert!(response.lines()[0].starts_with("info depth 0 score "));
        let best = response.lines()[1]
            .strip_prefix("bestmove ")
            .expect("bestmove line");
        assert!(resolve_uci_move(&root, best).is_some());
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn interruptible_depth_search_honors_external_stop_token() {
        let mut session = UciSession::new_interruptible();
        let root = session.engine().position().clone();
        let stop = session.stop_token();
        stop.stop();

        let response = session.handle_line("go depth 8");
        assert_eq!(response.lines().len(), 2);
        assert!(response.lines()[0].starts_with("info depth 0 score "));
        let best = response.lines()[1]
            .strip_prefix("bestmove ")
            .expect("bestmove line");
        assert!(resolve_uci_move(&root, best).is_some());
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn go_limits_compose_without_protocol_specific_search_logic() {
        let request = parse_go_request(&["go", "depth", "7", "nodes", "1234", "movetime", "50"])
            .expect("valid combined limits");
        let limits = request.into_limits(Color::White).expect("concrete limits");
        assert_eq!(limits.max_depth, 7);
        assert_eq!(limits.max_nodes, Some(1234));
        assert_eq!(limits.movetime, Some(Duration::from_millis(50)));

        let node_only = parse_go_request(&["go", "nodes", "8"])
            .expect("node request")
            .into_limits(Color::White)
            .expect("node limit");
        assert_eq!(node_only.max_depth, DEFAULT_LIMIT_DEPTH);
    }

    #[test]
    fn game_clock_budget_uses_side_to_move_and_increment() {
        let request = parse_go_request(&[
            "go", "wtime", "60000", "btime", "30000", "winc", "1000", "binc", "2000",
        ])
        .expect("clock request");

        let white = request.into_limits(Color::White).expect("white clock");
        assert_eq!(white.movetime, Some(Duration::from_millis(2_650)));

        let black = request.into_limits(Color::Black).expect("black clock");
        assert_eq!(black.movetime, Some(Duration::from_millis(2_450)));
    }

    #[test]
    fn movestogo_and_explicit_movetime_compose_conservatively() {
        let clock =
            parse_go_request(&["go", "wtime", "60000", "btime", "60000", "movestogo", "10"])
                .expect("clock request")
                .into_limits(Color::White)
                .expect("clock limits");
        assert_eq!(clock.movetime, Some(Duration::from_millis(5_700)));

        let capped = parse_go_request(&[
            "go", "movetime", "1000", "wtime", "60000", "btime", "60000", "winc", "1000",
        ])
        .expect("combined time request")
        .into_limits(Color::White)
        .expect("combined time limits");
        assert_eq!(capped.movetime, Some(Duration::from_millis(1_000)));
    }

    #[test]
    fn clock_go_uses_the_live_side_to_move() {
        let mut session = UciSession::new();
        assert!(
            session
                .handle_line("position startpos moves e2e4")
                .lines()
                .is_empty()
        );
        assert_eq!(session.engine().position().side_to_move(), Color::Black);

        let root = session.engine().position().clone();
        let response = session.handle_line("go depth 1 wtime 1 btime 60000 winc 0 binc 1000");
        assert_eq!(response.lines().len(), 2);
        assert!(response.lines()[0].starts_with("info depth 1 score "));
        let best = response.lines()[1]
            .strip_prefix("bestmove ")
            .expect("bestmove line");
        assert!(resolve_uci_move(&root, best).is_some());
        assert_eq!(session.engine().position(), &root);
    }

    #[test]
    fn incomplete_clock_for_side_to_move_is_rejected() {
        let request = parse_go_request(&["go", "wtime", "60000", "winc", "1000"])
            .expect("syntactically valid clock request");
        assert_eq!(
            request.into_limits(Color::Black),
            Err("go clock is missing btime for Black to move")
        );
    }

    #[test]
    fn node_and_clock_limits_are_preserved_together() {
        let limits = parse_go_request(&["go", "nodes", "5000", "wtime", "60000", "btime", "60000"])
            .expect("node plus clock")
            .into_limits(Color::White)
            .expect("combined limits");
        assert_eq!(limits.max_nodes, Some(5_000));
        assert_eq!(limits.movetime, Some(Duration::from_millis(1_900)));
    }

    #[test]
    fn unsupported_or_malformed_go_is_explicitly_rejected() {
        let mut session = UciSession::new();
        let unsupported = session.handle_line("go ponder 1000");
        assert!(unsupported.lines()[0].starts_with("info string unsupported go limit"));
        assert_eq!(unsupported.lines()[1], "bestmove 0000");

        let malformed = session.handle_line("go depth 0");
        assert!(malformed.lines()[0].contains("positive integer"));
        assert_eq!(malformed.lines()[1], "bestmove 0000");
    }

    #[test]
    fn quit_sets_session_flag() {
        let mut session = UciSession::new();
        assert!(session.handle_line("quit").should_quit());
    }
}
