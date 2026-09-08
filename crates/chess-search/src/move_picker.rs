use chess_core::{ChessMove, MAX_MOVES, MoveKind, MoveList, Position};

const ORDER_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 20_000];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stage {
    Tt,
    Tactical,
    Killer,
    Quiet,
    Done,
}

#[derive(Clone, Copy)]
struct ScoredQuiet {
    mv: ChessMove,
    score: i32,
    order: u16,
}

impl ScoredQuiet {
    const EMPTY: Self = Self {
        mv: ChessMove::NULL,
        score: 0,
        order: 0,
    };
}

/// Allocation-free staged selector over one owned legal-move buffer.
///
/// The picker mutates only the ordering of the freshly generated `MoveList`. It never allocates or
/// clones a board. The TT move is emitted first, tactical moves are selected lazily by a cheap
/// capture/promotion score, and untouched quiets follow in generator order.
///
/// Search-v2 experiments may use `next_scored`. That path scores every remaining ordinary quiet
/// exactly once when the quiet stage is first reached, sorts the cached `(score, generator-order)`
/// tuples without heap allocation, then consumes the ordered quiet batch linearly. This preserves
/// the useful history signal without the repeated O(n²) history-table probes of the first M6 probe.
pub(super) struct MovePicker<'a> {
    moves: &'a mut [ChessMove],
    tt_move: Option<ChessMove>,
    killers: [Option<ChessMove>; 2],
    killer_index: usize,
    stage: Stage,
    cursor: usize,
    quiet_ranked: bool,
}

impl<'a> MovePicker<'a> {
    pub(super) fn new(
        moves: &'a mut MoveList,
        tt_move: Option<ChessMove>,
        killers: [Option<ChessMove>; 2],
    ) -> Self {
        Self {
            moves: moves.as_mut_slice(),
            tt_move,
            killers,
            killer_index: 0,
            stage: Stage::Tt,
            cursor: 0,
            quiet_ranked: false,
        }
    }

    /// Select the next move using the accepted generator-order policy for ordinary quiets.
    pub(super) fn next(&mut self, position: &Position) -> Option<ChessMove> {
        loop {
            match self.stage {
                Stage::Tt => {
                    self.stage = Stage::Tactical;
                    if let Some(tt_move) = self.tt_move
                        && let Some(index) = self.moves[self.cursor..]
                            .iter()
                            .position(|&mv| mv == tt_move)
                            .map(|offset| self.cursor + offset)
                    {
                        self.moves.swap(self.cursor, index);
                        let mv = self.moves[self.cursor];
                        self.cursor += 1;
                        return Some(mv);
                    }
                }
                Stage::Tactical => {
                    if let Some(mv) = self.next_tactical(position) {
                        return Some(mv);
                    }
                    self.stage = Stage::Killer;
                }
                Stage::Killer => {
                    if let Some(mv) = self.next_killer() {
                        return Some(mv);
                    }
                    self.stage = Stage::Quiet;
                }
                Stage::Quiet => {
                    if self.cursor < self.moves.len() {
                        let mv = self.moves[self.cursor];
                        self.cursor += 1;
                        return Some(mv);
                    }
                    self.stage = Stage::Done;
                }
                Stage::Done => return None,
            }
        }
    }

    /// Select the next move while ranking ordinary quiets from a cached single scoring pass.
    ///
    /// TT, tactical and killer stages are identical to `next`. The supplied scorer is called once
    /// for each quiet left after those stages, regardless of how many quiets are ultimately searched.
    /// Equal scores preserve generator order, giving deterministic feature-off-like tie behaviour.
    pub(super) fn next_scored<F>(
        &mut self,
        position: &Position,
        quiet_score: &mut F,
    ) -> Option<ChessMove>
    where
        F: FnMut(ChessMove) -> i32,
    {
        loop {
            match self.stage {
                Stage::Tt => {
                    self.stage = Stage::Tactical;
                    if let Some(tt_move) = self.tt_move
                        && let Some(index) = self.moves[self.cursor..]
                            .iter()
                            .position(|&mv| mv == tt_move)
                            .map(|offset| self.cursor + offset)
                    {
                        self.moves.swap(self.cursor, index);
                        let mv = self.moves[self.cursor];
                        self.cursor += 1;
                        return Some(mv);
                    }
                }
                Stage::Tactical => {
                    if let Some(mv) = self.next_tactical(position) {
                        return Some(mv);
                    }
                    self.stage = Stage::Killer;
                }
                Stage::Killer => {
                    if let Some(mv) = self.next_killer() {
                        return Some(mv);
                    }
                    self.stage = Stage::Quiet;
                }
                Stage::Quiet => {
                    if !self.quiet_ranked {
                        self.rank_quiets_once(quiet_score);
                        self.quiet_ranked = true;
                    }
                    if self.cursor < self.moves.len() {
                        let mv = self.moves[self.cursor];
                        self.cursor += 1;
                        return Some(mv);
                    }
                    self.stage = Stage::Done;
                }
                Stage::Done => return None,
            }
        }
    }

    fn next_tactical(&mut self, position: &Position) -> Option<ChessMove> {
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

        let index = best_index?;
        self.moves.swap(self.cursor, index);
        let mv = self.moves[self.cursor];
        self.cursor += 1;
        Some(mv)
    }

    fn next_killer(&mut self) -> Option<ChessMove> {
        while self.killer_index < self.killers.len() {
            let killer = self.killers[self.killer_index];
            self.killer_index += 1;
            if let Some(killer) = killer
                && !is_tactical(killer)
                && let Some(index) = self.moves[self.cursor..]
                    .iter()
                    .position(|&mv| mv == killer)
                    .map(|offset| self.cursor + offset)
            {
                self.moves.swap(self.cursor, index);
                let mv = self.moves[self.cursor];
                self.cursor += 1;
                return Some(mv);
            }
        }
        None
    }

    fn rank_quiets_once<F>(&mut self, quiet_score: &mut F)
    where
        F: FnMut(ChessMove) -> i32,
    {
        let quiet_count = self.moves.len().saturating_sub(self.cursor);
        if quiet_count <= 1 {
            if quiet_count == 1 {
                let _ = quiet_score(self.moves[self.cursor]);
            }
            return;
        }

        let mut scored = [ScoredQuiet::EMPTY; MAX_MOVES];
        for (offset, &mv) in self.moves[self.cursor..].iter().enumerate() {
            scored[offset] = ScoredQuiet {
                mv,
                score: quiet_score(mv),
                order: offset as u16,
            };
        }

        scored[..quiet_count].sort_unstable_by(|left, right| {
            right
                .score
                .cmp(&left.score)
                .then_with(|| left.order.cmp(&right.order))
        });
        for (offset, scored_move) in scored[..quiet_count].iter().enumerate() {
            self.moves[self.cursor + offset] = scored_move.mv;
        }
    }
}

fn is_tactical(mv: ChessMove) -> bool {
    mv.kind().is_capture() || mv.kind().is_promotion()
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
    use core::cell::Cell;

    use chess_core::{Position, Square};

    use super::MovePicker;

    #[test]
    fn tt_move_is_returned_first_without_global_sorting() {
        let position = Position::startpos();
        let mut moves = position.legal_moves();
        let tt_move = moves.as_slice()[moves.len() - 1];
        let mut picker = MovePicker::new(&mut moves, Some(tt_move), [None; 2]);

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
        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);

        assert_eq!(picker.next(&position), Some(queen_capture));
    }

    #[test]
    fn quiet_killer_is_emitted_before_generator_order_quiets() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let killer = original.as_slice()[original.len() - 1];
        let mut moves = original.clone();
        let mut picker = MovePicker::new(&mut moves, None, [Some(killer), None]);

        assert_eq!(picker.next(&position), Some(killer));
    }

    #[test]
    fn scored_quiets_are_ranked_after_killers() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let killer = original.as_slice()[0];
        let preferred = original.as_slice()[original.len() - 1];
        let mut moves = original.clone();
        let mut picker = MovePicker::new(&mut moves, None, [Some(killer), None]);
        let mut score = |mv| i32::from(mv == preferred);

        assert_eq!(picker.next_scored(&position, &mut score), Some(killer));
        assert_eq!(picker.next_scored(&position, &mut score), Some(preferred));
    }

    #[test]
    fn scored_quiet_batch_calls_expensive_scorer_exactly_once_per_move() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let mut moves = original.clone();
        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        let calls = Cell::new(0usize);
        let mut score = |_| {
            calls.set(calls.get() + 1);
            0
        };

        while picker.next_scored(&position, &mut score).is_some() {}
        assert_eq!(calls.get(), original.len());
    }

    #[test]
    fn zero_quiet_scores_preserve_accepted_generator_order() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let mut default_moves = original.clone();
        let mut scored_moves = original.clone();
        let mut default_picker = MovePicker::new(&mut default_moves, None, [None; 2]);
        let mut scored_picker = MovePicker::new(&mut scored_moves, None, [None; 2]);
        let mut zero = |_| 0;

        loop {
            let expected = default_picker.next(&position);
            let actual = scored_picker.next_scored(&position, &mut zero);
            assert_eq!(actual, expected);
            if expected.is_none() {
                break;
            }
        }
    }

    #[test]
    fn every_legal_move_is_returned_exactly_once() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        let original = position.legal_moves();
        let mut scratch = original.clone();
        let mut picker = MovePicker::new(&mut scratch, Some(original.as_slice()[3]), [None; 2]);
        let mut picked = Vec::with_capacity(original.len());
        while let Some(mv) = picker.next(&position) {
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
