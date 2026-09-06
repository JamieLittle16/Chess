use crate::ChessMove;

/// Conservative fixed capacity above the maximum number of legal moves in a chess position.
pub const MAX_MOVES: usize = 256;

/// Allocation-free move buffer used by the chess core and search hot path.
#[derive(Clone)]
pub struct MoveList {
    moves: [ChessMove; MAX_MOVES],
    len: usize,
}

impl MoveList {
    #[must_use]
    pub const fn new() -> Self {
        Self {
            moves: [ChessMove::NULL; MAX_MOVES],
            len: 0,
        }
    }

    #[must_use]
    pub const fn len(&self) -> usize {
        self.len
    }

    #[must_use]
    pub const fn is_empty(&self) -> bool {
        self.len == 0
    }

    #[must_use]
    pub fn as_slice(&self) -> &[ChessMove] {
        &self.moves[..self.len]
    }

    pub(crate) fn push(&mut self, mv: ChessMove) {
        assert!(self.len < MAX_MOVES, "move list capacity exceeded");
        self.moves[self.len] = mv;
        self.len += 1;
    }
}

impl Default for MoveList {
    fn default() -> Self {
        Self::new()
    }
}

impl core::ops::Deref for MoveList {
    type Target = [ChessMove];

    fn deref(&self) -> &Self::Target {
        self.as_slice()
    }
}

impl<'a> IntoIterator for &'a MoveList {
    type Item = &'a ChessMove;
    type IntoIter = core::slice::Iter<'a, ChessMove>;

    fn into_iter(self) -> Self::IntoIter {
        self.as_slice().iter()
    }
}

impl core::fmt::Debug for MoveList {
    fn fmt(&self, f: &mut core::fmt::Formatter<'_>) -> core::fmt::Result {
        f.debug_list().entries(self.as_slice()).finish()
    }
}

#[cfg(test)]
mod tests {
    use core::mem::size_of;

    use crate::{ChessMove, MoveKind, Square};

    use super::{MAX_MOVES, MoveList};

    #[test]
    fn list_is_fixed_capacity_and_preserves_order() {
        let a1 = Square::from_file_rank(0, 0).expect("a1");
        let a2 = Square::from_file_rank(0, 1).expect("a2");
        let b1 = Square::from_file_rank(1, 0).expect("b1");
        let b2 = Square::from_file_rank(1, 1).expect("b2");
        let first = ChessMove::new(a1, a2, MoveKind::Quiet);
        let second = ChessMove::new(b1, b2, MoveKind::Quiet);

        let mut list = MoveList::new();
        list.push(first);
        list.push(second);

        assert_eq!(list.as_slice(), &[first, second]);
        assert_eq!(list.len(), 2);
        assert!(!list.is_empty());
        assert_eq!(
            size_of::<MoveList>(),
            MAX_MOVES * size_of::<ChessMove>() + size_of::<usize>()
        );
    }
}
