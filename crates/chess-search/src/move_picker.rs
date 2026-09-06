use chess_core::{ChessMove, Color, MoveKind, MoveList, Position};

const ORDER_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 20_000];
const HISTORY_ENTRIES: usize = 2 * 64 * 64;
const HISTORY_MAX: i32 = 16_384;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stage {
    Tt,
    Tactical,
    KillerOne,
    KillerTwo,
    Quiet,
    Done,
}

/// Compact butterfly-style quiet-history table.
///
/// Scores are indexed by side/from/to, so the entire table is 8,192 `i32`s (32 KiB). It is owned
/// by `Searcher`, allocated inline once, and never touched by chess-core. Positive cutoff bonuses use
/// bounded gravity rather than unbounded accumulation, keeping old information useful without
/// allowing a saturated entry to dominate forever.
pub(super) struct HistoryTable {
    scores: [i32; HISTORY_ENTRIES],
}

impl HistoryTable {
    pub(super) const fn new() -> Self {
        Self {
            scores: [0; HISTORY_ENTRIES],
        }
    }

    #[inline]
    pub(super) fn score(&self, side: Color, mv: ChessMove) -> i32 {
        self.scores[history_index(side, mv)]
    }

    pub(super) fn record_cutoff(&mut self, side: Color, mv: ChessMove, depth: u8) {
        debug_assert!(is_quiet(mv));
        let depth = i32::from(depth);
        let bonus = depth.saturating_mul(depth).clamp(1, 512);
        let entry = &mut self.scores[history_index(side, mv)];
        let gravity = (*entry).saturating_mul(bonus) / HISTORY_MAX;
        *entry = entry
            .saturating_add(bonus.saturating_sub(gravity))
            .clamp(-HISTORY_MAX, HISTORY_MAX);
    }
}

impl Default for HistoryTable {
    fn default() -> Self {
        Self::new()
    }
}

#[inline]
fn history_index(side: Color, mv: ChessMove) -> usize {
    side.index() * 64 * 64 + usize::from(mv.from().index()) * 64 + usize::from(mv.to().index())
}

/// Allocation-free staged selector over one owned legal-move buffer.
///
/// The picker mutates only the ordering of the freshly generated `MoveList`. It never allocates or
/// clones a board. The TT move is emitted first, tactical moves are selected lazily by a cheap
/// capture/promotion score, then up to two quiet killer moves are tried, followed by remaining quiet
/// moves selected lazily by history. A beta cutoff therefore avoids ordering work for moves never
/// searched, and no global sort is introduced.
pub(super) struct MovePicker<'a> {
    moves: &'a mut [ChessMove],
    tt_move: Option<ChessMove>,
    killers: [Option<ChessMove>; 2],
    stage: Stage,
    cursor: usize,
}

impl<'a> MovePicker<'a> {
    /// Construct the baseline picker without quiet-search heuristics.
    ///
    /// Quiescence uses this path so the history/killer experiment changes main-search quiet ordering
    /// only. Tactical qsearch ordering remains the accepted v1 behavior.
    pub(super) fn new(moves: &'a mut MoveList, tt_move: Option<ChessMove>) -> Self {
        Self::with_killers(moves, tt_move, [None, None])
    }

    pub(super) fn with_killers(
        moves: &'a mut MoveList,
        tt_move: Option<ChessMove>,
        killers: [Option<ChessMove>; 2],
    ) -> Self {
        Self {
            moves: moves.as_mut_slice(),
            tt_move,
            killers,
            stage: Stage::Tt,
            cursor: 0,
        }
    }

    /// Select the next move without quiet-history scoring.
    pub(super) fn next(&mut self, position: &Position) -> Option<ChessMove> {
        self.next_inner(position, None)
    }

    /// Select the next move while lazily consulting quiet history.
    pub(super) fn next_with_history(
        &mut self,
        position: &Position,
        history: &HistoryTable,
    ) -> Option<ChessMove> {
        self.next_inner(position, Some(history))
    }

    fn next_inner(
        &mut self,
        position: &Position,
        history: Option<&HistoryTable>,
    ) -> Option<ChessMove> {
        loop {
            match self.stage {
                Stage::Tt => {
                    self.stage = Stage::Tactical;
                    if let Some(tt_move) = self.tt_move
                        && let Some(index) = self.find_remaining(tt_move)
                    {
                        return Some(self.take(index));
                    }
                }
                Stage::Tactical => {
                    let mut best_index = None;
                    let mut best_score = i32::MIN;
                    for index in self.cursor..self.moves.len() {
                        let mv = self.moves[index];
                        if !is_tactical(mv) {
                            continue;
                        }
                        let score = tactical_score(position, mv);
                        if score > best_score {
                            best_score = score;
                            best_index = Some(index);
                        }
                    }

                    if let Some(index) = best_index {
                        return Some(self.take(index));
                    }
                    self.stage = Stage::KillerOne;
                }
                Stage::KillerOne => {
                    self.stage = Stage::KillerTwo;
                    if let Some(killer) = self.killers[0]
                        && is_quiet(killer)
                        && let Some(index) = self.find_remaining(killer)
                    {
                        return Some(self.take(index));
                    }
                }
                Stage::KillerTwo => {
                    self.stage = Stage::Quiet;
                    if let Some(killer) = self.killers[1]
                        && is_quiet(killer)
                        && let Some(index) = self.find_remaining(killer)
                    {
                        return Some(self.take(index));
                    }
                }
                Stage::Quiet => {
                    if self.cursor >= self.moves.len() {
                        self.stage = Stage::Done;
                        continue;
                    }

                    let index = if let Some(history) = history {
                        self.best_quiet_index(position.side_to_move(), history)
                    } else {
                        self.cursor
                    };
                    return Some(self.take(index));
                }
                Stage::Done => return None,
            }
        }
    }

    fn best_quiet_index(&self, side: Color, history: &HistoryTable) -> usize {
        let mut best_index = self.cursor;
        let mut best_score = i32::MIN;
        for index in self.cursor..self.moves.len() {
            let mv = self.moves[index];
            debug_assert!(is_quiet(mv));
            let score = history.score(side, mv);
            if score > best_score {
                best_score = score;
                best_index = index;
            }
        }
        best_index
    }

    fn find_remaining(&self, target: ChessMove) -> Option<usize> {
        self.moves[self.cursor..]
            .iter()
            .position(|&mv| mv == target)
            .map(|offset| self.cursor + offset)
    }

    fn take(&mut self, index: usize) -> ChessMove {
        self.moves.swap(self.cursor, index);
        let mv = self.moves[self.cursor];
        self.cursor += 1;
        mv
    }
}

#[inline]
fn is_tactical(mv: ChessMove) -> bool {
    mv.kind().is_capture() || mv.kind().is_promotion()
}

#[inline]
pub(super) fn is_quiet(mv: ChessMove) -> bool {
    !is_tactical(mv)
}

fn tactical_score(position: &Position, mv: ChessMove) -> i32 {
    let kind = mv.kind();
    let attacker = position
        .piece_at(mv.from())
        .map_or(0, |piece| ORDER_VALUES[piece.kind().index()]);

    let victim = if kind == MoveKind::EnPassant {
        ORDER_VALUES[0]
    } else {
        position
            .piece_at(mv.to())
            .map_or(0, |piece| ORDER_VALUES[piece.kind().index()])
    };

    let capture_score = if kind.is_capture() {
        victim.saturating_mul(32).saturating_sub(attacker)
    } else {
        0
    };
    let promotion_score = kind
        .promotion_piece()
        .map_or(0, |piece| ORDER_VALUES[piece.index()].saturating_mul(16));

    capture_score.saturating_add(promotion_score)
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position, Square};

    use super::{HistoryTable, MovePicker};

    #[test]
    fn tt_move_is_returned_first_without_global_sorting() {
        let position = Position::startpos();
        let mut moves = position.legal_moves();
        let tt_move = moves.as_slice()[moves.len() - 1];
        let mut picker = MovePicker::new(&mut moves, Some(tt_move));

        assert_eq!(picker.next(&position), Some(tt_move));
    }

    #[test]
    fn higher_value_capture_is_selected_before_lower_value_capture() {
        let position = Position::from_fen("7k/8/8/8/3q1r2/8/3Q4/K7 w - - 0 1").expect("valid FEN");
        let d2 = Square::from_file_rank(3, 1).expect("d2");
        let d4 = Square::from_file_rank(3, 3).expect("d4");
        let mut moves = position.legal_moves();
        let queen_capture = moves
            .as_slice()
            .iter()
            .copied()
            .find(|mv| mv.from() == d2 && mv.to() == d4)
            .expect("Qxd4 is legal");
        let mut picker = MovePicker::new(&mut moves, None);

        assert_eq!(picker.next(&position), Some(queen_capture));
    }

    #[test]
    fn killer_precedes_history_ranked_quiets() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let killer = original.as_slice()[7];
        let history_move = original.as_slice()[12];
        let mut history = HistoryTable::new();
        history.record_cutoff(Color::White, history_move, 12);

        let mut scratch = original.clone();
        let mut picker = MovePicker::with_killers(&mut scratch, None, [Some(killer), None]);
        assert_eq!(picker.next_with_history(&position, &history), Some(killer));
        assert_eq!(
            picker.next_with_history(&position, &history),
            Some(history_move)
        );
    }

    #[test]
    fn history_selects_best_remaining_quiet_without_sorting_all_moves() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let preferred = original.as_slice()[original.len() - 1];
        let mut history = HistoryTable::new();
        history.record_cutoff(Color::White, preferred, 10);

        let mut scratch = original.clone();
        let mut picker = MovePicker::with_killers(&mut scratch, None, [None, None]);
        assert_eq!(
            picker.next_with_history(&position, &history),
            Some(preferred)
        );
    }

    #[test]
    fn every_legal_move_is_returned_exactly_once() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        let original = position.legal_moves();
        let mut scratch = original.clone();
        let mut picker = MovePicker::with_killers(
            &mut scratch,
            Some(original.as_slice()[3]),
            [Some(original.as_slice()[4]), Some(original.as_slice()[5])],
        );
        let history = HistoryTable::new();
        let mut picked = Vec::with_capacity(original.len());
        while let Some(mv) = picker.next_with_history(&position, &history) {
            assert!(!picked.contains(&mv));
            picked.push(mv);
        }

        assert_eq!(picked.len(), original.len());
        assert!(
            original
                .as_slice()
                .iter()
                .all(|mv| picked.as_slice().contains(mv))
        );
    }
}
