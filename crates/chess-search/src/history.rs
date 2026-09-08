use chess_core::{Color, PieceKind, Square};

const MOVE_CONTEXTS: usize = PieceKind::ALL.len() * Square::COUNT as usize;
const MAIN_HISTORY_ENTRIES: usize = 2 * MOVE_CONTEXTS;
const CONTINUATION_HISTORY_ENTRIES: usize = MOVE_CONTEXTS * MOVE_CONTEXTS;
const HISTORY_LIMIT: i32 = 16_384;
const MAX_UPDATE: i32 = 2_048;

/// Compact move identity used by history heuristics.
///
/// Colour is intentionally omitted: side-to-move is explicit for main history, while continuation
/// history always links alternating plies. Encoding only piece kind and destination keeps the hot
/// context two bytes and the continuation table small enough to remain cache-friendly.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(transparent)]
pub(super) struct MoveContext(u16);

impl MoveContext {
    #[must_use]
    pub(super) const fn new(piece: PieceKind, to: Square) -> Self {
        Self((piece.index() * Square::COUNT as usize + to.index() as usize) as u16)
    }

    #[must_use]
    const fn index(self) -> usize {
        self.0 as usize
    }
}

/// Search-local move-ordering statistics for the M6 context-history experiment.
///
/// The tables are deliberately reset once per root search. They therefore learn across iterative
/// deepening iterations for one move without making tournament games depend on previous games in the
/// same engine process. The large continuation table is heap-owned once by `Searcher`; updates and
/// probes allocate nothing in the search hot path.
pub(super) struct HistoryTables {
    main: [i16; MAIN_HISTORY_ENTRIES],
    continuation: Box<[i16]>,
}

impl HistoryTables {
    #[must_use]
    pub(super) fn new() -> Self {
        Self {
            main: [0; MAIN_HISTORY_ENTRIES],
            continuation: vec![0; CONTINUATION_HISTORY_ENTRIES].into_boxed_slice(),
        }
    }

    pub(super) fn clear(&mut self) {
        self.main.fill(0);
        self.continuation.fill(0);
    }

    #[must_use]
    pub(super) fn score(
        &self,
        side: Color,
        previous: Option<MoveContext>,
        current: MoveContext,
    ) -> i32 {
        let mut score = i32::from(self.main[main_index(side, current)]);
        if let Some(previous) = previous {
            score += i32::from(self.continuation[continuation_index(previous, current)]);
        }
        score
    }

    /// Apply a bounded gravity update to both main and one-ply continuation history.
    pub(super) fn update(
        &mut self,
        side: Color,
        previous: Option<MoveContext>,
        current: MoveContext,
        bonus: i32,
    ) {
        update_entry(&mut self.main[main_index(side, current)], bonus);
        if let Some(previous) = previous {
            update_entry(
                &mut self.continuation[continuation_index(previous, current)],
                bonus,
            );
        }
    }
}

#[must_use]
pub(super) fn depth_bonus(depth: u8) -> i32 {
    let depth = i32::from(depth);
    (32 * depth * depth + 64 * depth).min(MAX_UPDATE)
}

#[inline]
fn main_index(side: Color, current: MoveContext) -> usize {
    side.index() * MOVE_CONTEXTS + current.index()
}

#[inline]
fn continuation_index(previous: MoveContext, current: MoveContext) -> usize {
    previous.index() * MOVE_CONTEXTS + current.index()
}

fn update_entry(entry: &mut i16, requested_bonus: i32) {
    let bonus = requested_bonus.clamp(-MAX_UPDATE, MAX_UPDATE);
    let current = i32::from(*entry);
    let gravity = current * bonus.abs() / HISTORY_LIMIT;
    let updated = (current + bonus - gravity).clamp(-HISTORY_LIMIT, HISTORY_LIMIT);
    *entry = updated as i16;
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, PieceKind, Square};

    use super::{HISTORY_LIMIT, HistoryTables, MoveContext, depth_bonus};

    fn context(kind: PieceKind, file: u8, rank: u8) -> MoveContext {
        MoveContext::new(
            kind,
            Square::from_file_rank(file, rank).expect("test square is on board"),
        )
    }

    #[test]
    fn main_history_is_side_specific_and_clearable() {
        let mut history = HistoryTables::new();
        let mv = context(PieceKind::Knight, 5, 2);
        history.update(Color::White, None, mv, 800);

        assert!(history.score(Color::White, None, mv) > 0);
        assert_eq!(history.score(Color::Black, None, mv), 0);
        history.clear();
        assert_eq!(history.score(Color::White, None, mv), 0);
    }

    #[test]
    fn continuation_history_only_rewards_matching_predecessor() {
        let mut history = HistoryTables::new();
        let previous = context(PieceKind::Pawn, 4, 3);
        let other_previous = context(PieceKind::Pawn, 3, 3);
        let current = context(PieceKind::Knight, 5, 2);

        history.update(Color::White, Some(previous), current, 700);
        let matching = history.score(Color::White, Some(previous), current);
        let nonmatching = history.score(Color::White, Some(other_previous), current);

        assert!(matching > nonmatching);
        assert!(nonmatching > 0, "main history is shared across predecessor contexts");
    }

    #[test]
    fn gravity_updates_remain_bounded_under_extreme_repetition() {
        let mut history = HistoryTables::new();
        let mv = context(PieceKind::Bishop, 2, 3);
        for _ in 0..10_000 {
            history.update(Color::White, None, mv, 10_000);
        }
        assert!(history.score(Color::White, None, mv) <= HISTORY_LIMIT);
        for _ in 0..20_000 {
            history.update(Color::White, None, mv, -10_000);
        }
        assert!(history.score(Color::White, None, mv) >= -HISTORY_LIMIT);
    }

    #[test]
    fn depth_bonus_is_monotone_and_capped() {
        let mut previous = 0;
        for depth in 1..=64 {
            let bonus = depth_bonus(depth);
            assert!(bonus >= previous);
            assert!(bonus <= 2_048);
            previous = bonus;
        }
    }
}
