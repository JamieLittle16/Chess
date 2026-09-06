use crate::Color;

/// A chess piece kind.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum PieceKind {
    Pawn = 0,
    Knight = 1,
    Bishop = 2,
    Rook = 3,
    Queen = 4,
    King = 5,
}

impl PieceKind {
    pub const ALL: [Self; 6] = [
        Self::Pawn,
        Self::Knight,
        Self::Bishop,
        Self::Rook,
        Self::Queen,
        Self::King,
    ];

    #[must_use]
    pub const fn index(self) -> usize {
        self as usize
    }
}

/// A coloured chess piece.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
pub struct Piece {
    color: Color,
    kind: PieceKind,
}

impl Piece {
    #[must_use]
    pub const fn new(color: Color, kind: PieceKind) -> Self {
        Self { color, kind }
    }

    #[must_use]
    pub const fn color(self) -> Color {
        self.color
    }

    #[must_use]
    pub const fn kind(self) -> PieceKind {
        self.kind
    }

    #[must_use]
    pub const fn slot(self) -> usize {
        self.color.index() * PieceKind::ALL.len() + self.kind.index()
    }

    #[must_use]
    pub const fn from_slot(slot: usize) -> Option<Self> {
        let (color, kind) = match slot {
            0 => (Color::White, PieceKind::Pawn),
            1 => (Color::White, PieceKind::Knight),
            2 => (Color::White, PieceKind::Bishop),
            3 => (Color::White, PieceKind::Rook),
            4 => (Color::White, PieceKind::Queen),
            5 => (Color::White, PieceKind::King),
            6 => (Color::Black, PieceKind::Pawn),
            7 => (Color::Black, PieceKind::Knight),
            8 => (Color::Black, PieceKind::Bishop),
            9 => (Color::Black, PieceKind::Rook),
            10 => (Color::Black, PieceKind::Queen),
            11 => (Color::Black, PieceKind::King),
            _ => return None,
        };
        Some(Self::new(color, kind))
    }

    #[must_use]
    pub fn from_fen_char(symbol: char) -> Option<Self> {
        let color = if symbol.is_ascii_uppercase() {
            Color::White
        } else if symbol.is_ascii_lowercase() {
            Color::Black
        } else {
            return None;
        };
        let kind = match symbol.to_ascii_lowercase() {
            'p' => PieceKind::Pawn,
            'n' => PieceKind::Knight,
            'b' => PieceKind::Bishop,
            'r' => PieceKind::Rook,
            'q' => PieceKind::Queen,
            'k' => PieceKind::King,
            _ => return None,
        };
        Some(Self::new(color, kind))
    }
}

#[cfg(test)]
mod tests {
    use crate::{Color, Piece, PieceKind};

    #[test]
    fn slots_round_trip() {
        for color in Color::ALL {
            for kind in PieceKind::ALL {
                let piece = Piece::new(color, kind);
                assert_eq!(Piece::from_slot(piece.slot()), Some(piece));
            }
        }
        assert_eq!(Piece::from_slot(12), None);
    }
}
