/// A chess side.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash)]
#[repr(u8)]
pub enum Color {
    White = 0,
    Black = 1,
}

impl Color {
    pub const ALL: [Self; 2] = [Self::White, Self::Black];

    #[must_use]
    pub const fn index(self) -> usize {
        self as usize
    }

    #[must_use]
    pub const fn opposite(self) -> Self {
        match self {
            Self::White => Self::Black,
            Self::Black => Self::White,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::Color;

    #[test]
    fn opposite_is_an_involution() {
        for color in Color::ALL {
            assert_eq!(color.opposite().opposite(), color);
        }
    }
}
