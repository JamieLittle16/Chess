use core::fmt;

/// A board square encoded from `a1 = 0` through `h8 = 63`.
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
#[repr(transparent)]
pub struct Square(u8);

impl Square {
    pub const COUNT: u8 = 64;

    #[must_use]
    pub const fn from_index(index: u8) -> Option<Self> {
        if index < Self::COUNT {
            Some(Self(index))
        } else {
            None
        }
    }

    #[must_use]
    pub const fn from_file_rank(file: u8, rank: u8) -> Option<Self> {
        if file < 8 && rank < 8 {
            Some(Self(rank * 8 + file))
        } else {
            None
        }
    }

    #[must_use]
    pub const fn index(self) -> u8 {
        self.0
    }

    #[must_use]
    pub const fn file(self) -> u8 {
        self.0 & 7
    }

    #[must_use]
    pub const fn rank(self) -> u8 {
        self.0 >> 3
    }

    #[must_use]
    pub const fn bit(self) -> u64 {
        1_u64 << self.0
    }
}

impl fmt::Display for Square {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let file = char::from(b'a' + self.file());
        let rank = char::from(b'1' + self.rank());
        write!(f, "{file}{rank}")
    }
}

impl fmt::Debug for Square {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(self, f)
    }
}

#[cfg(test)]
mod tests {
    use super::Square;

    #[test]
    fn indexing_matches_chess_coordinates() {
        let a1 = Square::from_file_rank(0, 0).expect("a1");
        let h8 = Square::from_file_rank(7, 7).expect("h8");
        assert_eq!(a1.index(), 0);
        assert_eq!(a1.to_string(), "a1");
        assert_eq!(h8.index(), 63);
        assert_eq!(h8.to_string(), "h8");
        assert!(Square::from_index(64).is_none());
        assert!(Square::from_file_rank(8, 0).is_none());
    }
}
