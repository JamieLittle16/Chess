//! Correctness-first chess domain and position representation.
//!
//! This crate intentionally contains no search, evaluation, protocol, training, or browser logic.

mod attacks;
mod bitboard;
mod chess_move;
mod color;
mod draw;
mod fen;
mod move_list;
mod movegen;
mod perft;
mod piece;
mod position;
mod reference;
mod reversible;
mod square;
mod zobrist;

pub use attacks::{
    bishop_attacks, is_square_attacked, king_attacks, knight_attacks, pawn_attacks, queen_attacks,
    rook_attacks,
};
pub use bitboard::{BitIter, Bitboard};
pub use chess_move::{ChessMove, MoveKind};
pub use color::Color;
pub use fen::{FenError, STARTPOS_FEN};
pub use move_list::{MAX_MOVES, MoveList};
pub use movegen::{
    generate_legal_moves, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
};
pub use perft::{perft, perft_mut};
pub use piece::{Piece, PieceKind};
pub use position::{CastlingRights, Position};
pub use reversible::Undo;
pub use square::Square;
pub use zobrist::ZobristKey;
