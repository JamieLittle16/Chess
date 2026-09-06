use core::ops::{BitAnd, BitOr, BitXor, Not};

use crate::Square;

/// A set of board squares packed into one machine word.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Hash)]
#[repr(transparent)]
pub struct Bitboard(u64);

impl Bitboard {
    pub const EMPTY: Self = Self(0);
    pub const FULL: Self = Self(u64::MAX);

    #[must_use]
    pub const fn from_raw(bits: u64) -> Self {
        Self(bits)
    }

    #[must_use]
    pub const fn raw(self) -> u64 {
        self.0
    }

    #[must_use]
    pub const fn is_empty(self) -> bool {
        self.0 == 0
    }

    #[must_use]
    pub const fn count(self) -> u32 {
        self.0.count_ones()
    }

    #[must_use]
    pub const fn contains(self, square: Square) -> bool {
        self.0 & square.bit() != 0
    }

    #[must_use]
    pub const fn with(self, square: Square) -> Self {
        Self(self.0 | square.bit())
    }

    #[must_use]
    pub const fn without(self, square: Square) -> Self {
        Self(self.0 & !square.bit())
    }

    pub fn pop_lsb(&mut self) -> Option<Square> {
        if self.is_empty() {
            return None;
        }
        let index = self.0.trailing_zeros() as u8;
        self.0 &= self.0 - 1;
        Square::from_index(index)
    }

    #[must_use]
    pub const fn iter(self) -> BitIter {
        BitIter(self)
    }
}

impl BitAnd for Bitboard {
    type Output = Self;

    fn bitand(self, rhs: Self) -> Self::Output {
        Self(self.0 & rhs.0)
    }
}

impl BitOr for Bitboard {
    type Output = Self;

    fn bitor(self, rhs: Self) -> Self::Output {
        Self(self.0 | rhs.0)
    }
}

impl BitXor for Bitboard {
    type Output = Self;

    fn bitxor(self, rhs: Self) -> Self::Output {
        Self(self.0 ^ rhs.0)
    }
}

impl Not for Bitboard {
    type Output = Self;

    fn not(self) -> Self::Output {
        Self(!self.0)
    }
}

/// Iterator over occupied squares from least to greatest square index.
pub struct BitIter(Bitboard);

impl Iterator for BitIter {
    type Item = Square;

    fn next(&mut self) -> Option<Self::Item> {
        self.0.pop_lsb()
    }

    fn size_hint(&self) -> (usize, Option<usize>) {
        let remaining = self.0.count() as usize;
        (remaining, Some(remaining))
    }
}

impl ExactSizeIterator for BitIter {}

impl IntoIterator for Bitboard {
    type Item = Square;
    type IntoIter = BitIter;

    fn into_iter(self) -> Self::IntoIter {
        self.iter()
    }
}

#[cfg(test)]
mod tests {
    use crate::Square;

    use super::Bitboard;

    #[test]
    fn iteration_clears_each_bit_once() {
        let a1 = Square::from_index(0).expect("a1");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let h8 = Square::from_index(63).expect("h8");
        let board = Bitboard::EMPTY.with(d4).with(h8).with(a1);
        let squares: Vec<_> = board.into_iter().collect();
        assert_eq!(squares, vec![a1, d4, h8]);
        assert_eq!(board.count(), 3);
    }
}
