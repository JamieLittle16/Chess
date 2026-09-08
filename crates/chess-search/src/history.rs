use chess_core::{Color, PieceKind, Square};

const MOVE_CONTEXTS: usize = PieceKind::ALL.len() * Square::COUNT as usize;
const MAIN_HISTORY_ENTRIES: usize = 2 * MOVE_CONTEXTS;
const CONTINUATION_HISTORY_ENTRIES: usize = MOVE_CONTEXTS * MOVE_CONTEXTS;
const HISTORY_LIMIT: i32 = 16_384;
const MAX_UPDATE: i32 = 2_048;

/// Compact move identity used by quiet-history heuristics.
///
/// Colour is intentionally omitted: side-to-move is explicit for main history, while continuation
/// history links alternating plies. Encoding only piece kind and destination keeps the hot context
/// two bytes and the continuation tables compact enough to remain cache-friendly.
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

/// Search-local main + reply + same-side continuation history.
///
/// `reply` conditions a quiet on the opponent's immediately preceding move. `plan` conditions it on
/// our own previous move two plies ago, which captures a different signal: whether a move tends to
/// continue a successful same-side plan. Keeping the two channels separate avoids conflating those
/// semantics while retaining O(1), allocation-free hot-path probes.
///
/// Tables are cleared once per top-level search, so iterative deepening can teach later iterations
/// without making tournament games depend on earlier games in the same process.
pub(super) struct HistoryTables {
    main: [i16; MAIN_HISTORY_ENTRIES],
    reply: Box<[i16]>,
    plan: Box<[i16]>,
}

impl HistoryTables {
    #[must_use]
    pub(super) fn new() -> Self {
        Self {
            main: [0; MAIN_HISTORY_ENTRIES],
            reply: vec![0; CONTINUATION_HISTORY_ENTRIES].into_boxed_slice(),
            plan: vec![0; CONTINUATION_HISTORY_ENTRIES].into_boxed_slice(),
        }
    }

    pub(super) fn clear(&mut self) {
        self.main.fill(0);
        self.reply.fill(0);
        self.plan.fill(0);
    }

    #[must_use]
    pub(super) fn score(
        &self,
        side: Color,
        previous_reply: Option<MoveContext>,
        previous_plan: Option<MoveContext>,
        current: MoveContext,
    ) -> i32 {
        let mut score = i32::from(self.main[main_index(side, current)]);
        if let Some(previous) = previous_reply {
            score += i32::from(self.reply[continuation_index(previous, current)]);
        }
        if let Some(previous) = previous_plan {
            // Same-side plan history is deliberately lower weight in generation one. It should
            // refine an established main/reply signal, not dominate ordering from sparse evidence.
            score += i32::from(self.plan[continuation_index(previous, current)]) / 2;
        }
        score
    }

    /// Apply bounded gravity updates to main, one-ply reply and two-ply plan history.
    pub(super) fn update(
        &mut self,
        side: Color,
        previous_reply: Option<MoveContext>,
        previous_plan: Option<MoveContext>,
        current: MoveContext,
        bonus: i32,
    ) {
        update_entry(&mut self.main[main_index(side, current)], bonus);
        if let Some(previous) = previous_reply {
            update_entry(
                &mut self.reply[continuation_index(previous, current)],
                bonus,
            );
        }
        if let Some(previous) = previous_plan {
            update_entry(
                &mut self.plan[continuation_index(previous, current)],
                bonus / 2,
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
        history.update(Color::White, None, None, mv, 800);

        assert!(history.score(Color::White, None, None, mv) > 0);
        assert_eq!(history.score(Color::Black, None, None, mv), 0);
        history.clear();
        assert_eq!(history.score(Color::White, None, None, mv), 0);
    }

    #[test]
    fn reply_history_only_rewards_matching_opponent_predecessor() {
        let mut history = HistoryTables::new();
        let previous = context(PieceKind::Pawn, 4, 3);
        let other_previous = context(PieceKind::Pawn, 3, 3);
        let current = context(PieceKind::Knight, 5, 2);

        history.update(Color::White, Some(previous), None, current, 700);
        let matching = history.score(Color::White, Some(previous), None, current);
        let nonmatching = history.score(Color::White, Some(other_previous), None, current);

        assert!(matching > nonmatching);
        assert!(
            nonmatching > 0,
            "main history is shared across predecessor contexts"
        );
    }

    #[test]
    fn two_ply_plan_history_is_distinct_and_lower_weight() {
        let mut history = HistoryTables::new();
        let reply = context(PieceKind::Pawn, 4, 4);
        let plan = context(PieceKind::Knight, 2, 2);
        let other_plan = context(PieceKind::Knight, 5, 2);
        let current = context(PieceKind::Bishop, 5, 3);

        history.update(Color::White, Some(reply), Some(plan), current, 800);
        let matching = history.score(Color::White, Some(reply), Some(plan), current);
        let wrong_plan = history.score(Color::White, Some(reply), Some(other_plan), current);
        let no_plan = history.score(Color::White, Some(reply), None, current);

        assert!(matching > wrong_plan);
        assert_eq!(wrong_plan, no_plan);
        assert!(matching - no_plan < no_plan, "plan channel is a refinement");
    }

    #[test]
    fn gravity_updates_remain_bounded_under_extreme_repetition() {
        let mut history = HistoryTables::new();
        let mv = context(PieceKind::Bishop, 2, 3);
        for _ in 0..10_000 {
            history.update(Color::White, None, None, mv, 10_000);
        }
        assert!(history.score(Color::White, None, None, mv) <= HISTORY_LIMIT);
        for _ in 0..20_000 {
            history.update(Color::White, None, None, mv, -10_000);
        }
        assert!(history.score(Color::White, None, None, mv) >= -HISTORY_LIMIT);
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
