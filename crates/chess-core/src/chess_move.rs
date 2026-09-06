use crate::{PieceKind, Square};

/// Encodes the semantic kind of a chess move in four bits.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum MoveKind {
    Quiet = 0,
    DoublePawnPush = 1,
    KingCastle = 2,
    QueenCastle = 3,
    Capture = 4,
    EnPassant = 5,
    PromoteKnight = 6,
    PromoteBishop = 7,
    PromoteRook = 8,
    PromoteQueen = 9,
    PromoteCaptureKnight = 10,
    PromoteCaptureBishop = 11,
    PromoteCaptureRook = 12,
    PromoteCaptureQueen = 13,
}

impl MoveKind {
    #[must_use]
    pub const fn is_capture(self) -> bool {
        matches!(
            self,
            Self::Capture
                | Self::EnPassant
                | Self::PromoteCaptureKnight
                | Self::PromoteCaptureBishop
                | Self::PromoteCaptureRook
                | Self::PromoteCaptureQueen
        )
    }

    #[must_use]
    pub const fn is_promotion(self) -> bool {
        matches!(
            self,
            Self::PromoteKnight
                | Self::PromoteBishop
                | Self::PromoteRook
                | Self::PromoteQueen
                | Self::PromoteCaptureKnight
                | Self::PromoteCaptureBishop
                | Self::PromoteCaptureRook
                | Self::PromoteCaptureQueen
        )
    }

    #[must_use]
    pub const fn promotion_piece(self) -> Option<PieceKind> {
        match self {
            Self::PromoteKnight | Self::PromoteCaptureKnight => Some(PieceKind::Knight),
            Self::PromoteBishop | Self::PromoteCaptureBishop => Some(PieceKind::Bishop),
            Self::PromoteRook | Self::PromoteCaptureRook => Some(PieceKind::Rook),
            Self::PromoteQueen | Self::PromoteCaptureQueen => Some(PieceKind::Queen),
            _ => None,
        }
    }

    fn from_tag(tag: u8) -> Self {
        match tag {
            0 => Self::Quiet,
            1 => Self::DoublePawnPush,
            2 => Self::KingCastle,
            3 => Self::QueenCastle,
            4 => Self::Capture,
            5 => Self::EnPassant,
            6 => Self::PromoteKnight,
            7 => Self::PromoteBishop,
            8 => Self::PromoteRook,
            9 => Self::PromoteQueen,
            10 => Self::PromoteCaptureKnight,
            11 => Self::PromoteCaptureBishop,
            12 => Self::PromoteCaptureRook,
            13 => Self::PromoteCaptureQueen,
            _ => unreachable!("ChessMove stores only MoveKind tags created by ChessMove::new"),
        }
    }
}

/// A compact chess move: six bits each for source/destination and four for move kind.
#[derive(Clone, Copy, PartialEq, Eq, Hash)]
#[repr(transparent)]
pub struct ChessMove(u16);

impl ChessMove {
    /// Sentinel used only in unused slots of fixed-capacity move buffers.
    pub const NULL: Self = Self(0);

    #[must_use]
    pub const fn new(from: Square, to: Square, kind: MoveKind) -> Self {
        Self((from.index() as u16) << 6 | to.index() as u16 | ((kind as u16) << 12))
    }

    #[must_use]
    pub const fn from(self) -> Square {
        match Square::from_index(((self.0 >> 6) & 0x3f) as u8) {
            Some(square) => square,
            None => unreachable!(),
        }
    }

    #[must_use]
    pub const fn to(self) -> Square {
        match Square::from_index((self.0 & 0x3f) as u8) {
            Some(square) => square,
            None => unreachable!(),
        }
    }

    #[must_use]
    pub fn kind(self) -> MoveKind {
        MoveKind::from_tag((self.0 >> 12) as u8)
    }

    #[must_use]
    pub const fn raw(self) -> u16 {
        self.0
    }
}

impl core::fmt::Debug for ChessMove {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        write!(f, "{}{}:{:?}", self.from(), self.to(), self.kind())
    }
}

#[cfg(test)]
mod tests {
    use core::mem::size_of;

    use crate::{ChessMove, MoveKind, PieceKind, Square};

    #[test]
    fn move_is_two_bytes_and_round_trips() {
        let from = Square::from_file_rank(4, 1).expect("e2");
        let to = Square::from_file_rank(4, 3).expect("e4");
        let mv = ChessMove::new(from, to, MoveKind::DoublePawnPush);
        assert_eq!(size_of::<ChessMove>(), 2);
        assert_eq!(mv.from(), from);
        assert_eq!(mv.to(), to);
        assert_eq!(mv.kind(), MoveKind::DoublePawnPush);
    }

    #[test]
    fn promotion_kind_maps_to_promoted_piece() {
        assert_eq!(MoveKind::PromoteQueen.promotion_piece(), Some(PieceKind::Queen));
        assert_eq!(
            MoveKind::PromoteCaptureKnight.promotion_piece(),
            Some(PieceKind::Knight)
        );
        assert_eq!(MoveKind::Capture.promotion_piece(), None);
    }
}
