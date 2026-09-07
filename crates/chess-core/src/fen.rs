use core::fmt::{self, Write as _};

use crate::{CastlingRights, Color, Piece, PieceKind, Position, Square};

pub const STARTPOS_FEN: &str = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

/// Error returned by strict FEN parsing.
#[derive(Clone, Debug, PartialEq, Eq)]
pub enum FenError {
    FieldCount,
    RankCount,
    RankWidth,
    InvalidPiece(char),
    InvalidSide,
    InvalidCastling(char),
    InvalidEnPassant,
    InvalidHalfmove,
    InvalidFullmove,
    OverlappingPieces,
    InternalInvariant,
}

impl fmt::Display for FenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::FieldCount => f.write_str("FEN must contain exactly six fields"),
            Self::RankCount => f.write_str("FEN board must contain exactly eight ranks"),
            Self::RankWidth => f.write_str("each FEN rank must describe exactly eight files"),
            Self::InvalidPiece(piece) => write!(f, "invalid FEN piece symbol: {piece}"),
            Self::InvalidSide => f.write_str("FEN side-to-move field must be w or b"),
            Self::InvalidCastling(symbol) => write!(f, "invalid FEN castling symbol: {symbol}"),
            Self::InvalidEnPassant => f.write_str("invalid FEN en-passant square"),
            Self::InvalidHalfmove => f.write_str("invalid FEN halfmove clock"),
            Self::InvalidFullmove => f.write_str("invalid FEN fullmove number"),
            Self::OverlappingPieces => f.write_str("multiple pieces occupy one square"),
            Self::InternalInvariant => f.write_str("parsed FEN violates position cache invariants"),
        }
    }
}

impl std::error::Error for FenError {}

impl Position {
    /// Serialize the complete position as canonical six-field FEN.
    ///
    /// This is intentionally the inverse of [`Position::from_fen`]: all rule-relevant state and
    /// both clocks are preserved, while board runs and castling symbols use canonical ordering.
    /// Search hot paths should not call this; it exists for protocol boundaries, diagnostics and
    /// offline corpus generation.
    #[must_use]
    pub fn to_fen(&self) -> String {
        let mut output = String::with_capacity(96);

        for rank in (0_u8..8).rev() {
            if rank != 7 {
                output.push('/');
            }
            let mut empty = 0_u8;
            for file in 0_u8..8 {
                let square = Square::from_file_rank(file, rank).expect("board coordinates are valid");
                if let Some(piece) = self.piece_at(square) {
                    if empty != 0 {
                        output.push(char::from(b'0' + empty));
                        empty = 0;
                    }
                    output.push(piece_fen_char(piece));
                } else {
                    empty += 1;
                }
            }
            if empty != 0 {
                output.push(char::from(b'0' + empty));
            }
        }

        output.push(' ');
        output.push(match self.side_to_move() {
            Color::White => 'w',
            Color::Black => 'b',
        });
        output.push(' ');

        let rights = self.castling_rights();
        if rights == CastlingRights::NONE {
            output.push('-');
        } else {
            for (flag, symbol) in [
                (CastlingRights::WHITE_KING, 'K'),
                (CastlingRights::WHITE_QUEEN, 'Q'),
                (CastlingRights::BLACK_KING, 'k'),
                (CastlingRights::BLACK_QUEEN, 'q'),
            ] {
                if rights.contains(flag) {
                    output.push(symbol);
                }
            }
        }

        output.push(' ');
        match self.en_passant() {
            Some(square) => write!(output, "{square}").expect("writing to String cannot fail"),
            None => output.push('-'),
        }
        write!(
            output,
            " {} {}",
            self.halfmove_clock(),
            self.fullmove_number()
        )
        .expect("writing to String cannot fail");
        output
    }
}

fn piece_fen_char(piece: Piece) -> char {
    let lower = match piece.kind() {
        PieceKind::Pawn => 'p',
        PieceKind::Knight => 'n',
        PieceKind::Bishop => 'b',
        PieceKind::Rook => 'r',
        PieceKind::Queen => 'q',
        PieceKind::King => 'k',
    };
    match piece.color() {
        Color::White => lower.to_ascii_uppercase(),
        Color::Black => lower,
    }
}

pub(crate) fn parse(fen: &str) -> Result<Position, FenError> {
    let mut fields = fen.split_whitespace();
    let board = fields.next().ok_or(FenError::FieldCount)?;
    let side = fields.next().ok_or(FenError::FieldCount)?;
    let castling = fields.next().ok_or(FenError::FieldCount)?;
    let en_passant = fields.next().ok_or(FenError::FieldCount)?;
    let halfmove = fields.next().ok_or(FenError::FieldCount)?;
    let fullmove = fields.next().ok_or(FenError::FieldCount)?;
    if fields.next().is_some() {
        return Err(FenError::FieldCount);
    }

    let mut position = Position::empty();
    parse_board(board, &mut position)?;

    position.set_side_to_move(match side {
        "w" => Color::White,
        "b" => Color::Black,
        _ => return Err(FenError::InvalidSide),
    });
    position.set_castling_rights(parse_castling(castling)?);
    position.set_en_passant(parse_en_passant(en_passant)?);

    let halfmove = halfmove
        .parse::<u16>()
        .map_err(|_| FenError::InvalidHalfmove)?;
    let fullmove = fullmove
        .parse::<u16>()
        .map_err(|_| FenError::InvalidFullmove)?;
    if fullmove == 0 {
        return Err(FenError::InvalidFullmove);
    }
    position.set_clocks(halfmove, fullmove);

    if !position.structural_invariants_hold() {
        return Err(FenError::InternalInvariant);
    }
    Ok(position)
}

fn parse_board(board: &str, position: &mut Position) -> Result<(), FenError> {
    let mut ranks = board.split('/');
    for fen_rank in 0_u8..8 {
        let rank_text = ranks.next().ok_or(FenError::RankCount)?;
        let board_rank = 7 - fen_rank;
        let mut file = 0_u8;

        for symbol in rank_text.chars() {
            if let Some(empty) = symbol.to_digit(10) {
                if empty == 0 || empty > 8 {
                    return Err(FenError::RankWidth);
                }
                file = file.checked_add(empty as u8).ok_or(FenError::RankWidth)?;
                if file > 8 {
                    return Err(FenError::RankWidth);
                }
                continue;
            }

            let piece = Piece::from_fen_char(symbol).ok_or(FenError::InvalidPiece(symbol))?;
            if file >= 8 {
                return Err(FenError::RankWidth);
            }
            let square = Square::from_file_rank(file, board_rank).ok_or(FenError::RankWidth)?;
            position.put_piece(piece, square)?;
            file += 1;
        }

        if file != 8 {
            return Err(FenError::RankWidth);
        }
    }
    if ranks.next().is_some() {
        return Err(FenError::RankCount);
    }
    Ok(())
}

fn parse_castling(field: &str) -> Result<CastlingRights, FenError> {
    if field == "-" {
        return Ok(CastlingRights::NONE);
    }
    if field.is_empty() {
        return Err(FenError::InvalidCastling('-'));
    }

    let mut rights = CastlingRights::NONE;
    for symbol in field.chars() {
        let flag = match symbol {
            'K' => CastlingRights::WHITE_KING,
            'Q' => CastlingRights::WHITE_QUEEN,
            'k' => CastlingRights::BLACK_KING,
            'q' => CastlingRights::BLACK_QUEEN,
            _ => return Err(FenError::InvalidCastling(symbol)),
        };
        if rights.contains(flag) {
            return Err(FenError::InvalidCastling(symbol));
        }
        rights = rights.union(flag);
    }
    Ok(rights)
}

fn parse_en_passant(field: &str) -> Result<Option<Square>, FenError> {
    if field == "-" {
        return Ok(None);
    }
    let bytes = field.as_bytes();
    if bytes.len() != 2 || !(b'a'..=b'h').contains(&bytes[0]) || !(b'1'..=b'8').contains(&bytes[1])
    {
        return Err(FenError::InvalidEnPassant);
    }
    let file = bytes[0] - b'a';
    let rank = bytes[1] - b'1';
    if rank != 2 && rank != 5 {
        return Err(FenError::InvalidEnPassant);
    }
    Square::from_file_rank(file, rank)
        .map(Some)
        .ok_or(FenError::InvalidEnPassant)
}

#[cfg(test)]
mod tests {
    use crate::{CastlingRights, Color, FenError, Piece, PieceKind, Position, Square};

    use super::STARTPOS_FEN;

    #[test]
    fn start_position_parses_with_expected_state() {
        let position = Position::from_fen(STARTPOS_FEN).expect("valid start position");
        assert_eq!(position.side_to_move(), Color::White);
        assert_eq!(position.occupied().count(), 32);
        assert_eq!(position.pieces(Color::White, PieceKind::Pawn).count(), 8);
        assert_eq!(position.pieces(Color::Black, PieceKind::Pawn).count(), 8);
        assert_eq!(position.castling_rights(), CastlingRights::ALL);
        assert!(position.en_passant().is_none());
        assert_eq!(position.halfmove_clock(), 0);
        assert_eq!(position.fullmove_number(), 1);
        assert!(position.structural_invariants_hold());
        assert_eq!(position.to_fen(), STARTPOS_FEN);

        let e1 = Square::from_file_rank(4, 0).expect("e1");
        assert_eq!(
            position.piece_at(e1),
            Some(Piece::new(Color::White, PieceKind::King))
        );
    }

    #[test]
    fn parser_rejects_bad_shape_and_en_passant() {
        assert_eq!(
            Position::from_fen("8/8/8/8/8/8/8 w - - 0 1"),
            Err(FenError::RankCount)
        );
        assert_eq!(
            Position::from_fen("8/8/8/8/8/8/8/8 w - e4 0 1"),
            Err(FenError::InvalidEnPassant)
        );
    }

    #[test]
    fn parser_handles_a_nontrivial_position() {
        let fen = "r3k2r/pppq1ppp/2npbn2/3Np3/2B1P3/2N2Q1P/PPP2PP1/R3K2R b KQkq - 4 10";
        let position = Position::from_fen(fen).expect("valid FEN");
        assert_eq!(position.side_to_move(), Color::Black);
        assert_eq!(position.fullmove_number(), 10);
        assert_eq!(position.halfmove_clock(), 4);
        assert!(position.structural_invariants_hold());
        assert_eq!(position.to_fen(), fen);
        assert_eq!(Position::from_fen(&position.to_fen()), Ok(position));
    }

    #[test]
    fn serializer_preserves_en_passant_and_partial_castling_rights() {
        let fen = "4k2r/8/8/3pP3/8/8/8/R3K3 w Qk d6 17 42";
        let position = Position::from_fen(fen).expect("valid FEN");
        assert_eq!(position.to_fen(), fen);
        assert_eq!(Position::from_fen(&position.to_fen()), Ok(position));
    }
}
