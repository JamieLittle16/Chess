//! Correctness-first chess domain and position representation.
//!
//! This crate intentionally contains no search, evaluation, protocol, training, or browser logic.

mod attacks;
mod bitboard;
mod chess_move;
mod color;
mod fen;
mod move_list;
mod movegen;
mod perft;
mod piece;
mod position;
mod reference;
mod reversible;
mod square;

pub use attacks::{
    bishop_attacks, is_square_attacked, king_attacks, knight_attacks, pawn_attacks, queen_attacks,
    rook_attacks,
};
pub use bitboard::{BitIter, Bitboard};
pub use chess_move::{ChessMove, MoveKind};
pub use color::Color;
pub use fen::{FenError, STARTPOS_FEN};
pub use move_list::{MAX_MOVES, MoveList};
pub use movegen::generate_legal_moves;
pub use perft::perft;
pub use piece::{Piece, PieceKind};
pub use position::{CastlingRights, Position};
pub use reversible::Undo;
pub use square::Square;
