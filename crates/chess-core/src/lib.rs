//! Correctness-first chess domain and position representation.
//!
//! This crate intentionally contains no search, evaluation, protocol, training, or browser logic.

mod bitboard;
mod chess_move;
mod color;
mod fen;
mod piece;
mod position;
mod square;

pub use bitboard::{BitIter, Bitboard};
pub use chess_move::{ChessMove, MoveKind};
pub use color::Color;
pub use fen::{FenError, STARTPOS_FEN};
pub use piece::{Piece, PieceKind};
pub use position::{CastlingRights, Position};
pub use square::Square;
