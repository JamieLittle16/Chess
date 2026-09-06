use chess_core::{ChessMove, MoveKind, MoveList, Position};

const ORDER_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 20_000];

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum Stage {
    Tt,
    Tactical,
    Quiet,
    Done,
}

/// Allocation-free staged selector over one owned legal-move buffer.
///
/// The picker mutates only the ordering of the freshly generated `MoveList`. It never allocates or
/// clones a board. The TT move is emitted first, tactical moves are selected lazily by a cheap
/// capture/promotion score, and untouched quiets follow in generator order. Lazy selection means a
/// beta cutoff avoids scoring/sorting moves that are never searched.
///
/// This is deliberately a substrate rather than a final ordering policy. SEE, killers, history and
/// counter-moves can become additional stages without changing search ownership or move generation.
pub(super) struct MovePicker<'a> {
    moves: &'a mut [ChessMove],
    tt_move: Option<ChessMove>,
    stage: Stage,
    cursor: usize,
}

impl<'a> MovePicker<'a> {
    pub(super) fn new(moves: &'a mut MoveList, tt_move: Option<ChessMove>) -> Self {
        Self {
            moves: moves.as_mut_slice(),
            tt_move,
            stage: Stage::Tt,
            cursor: 0,
        }
    }

    /// Select the next move, doing only the ordering work required to produce that move.
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
                        self.moves.swap(self.cursor, index);
                        let mv = self.moves[self.cursor];
                        self.cursor += 1;
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
    use chess_core::{Position, Square};

    use super::MovePicker;

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
        let position =
            Position::from_fen("7k/8/8/8/3q1r2/8/3Q4/K7 w - - 0 1").expect("valid FEN");
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
    fn every_legal_move_is_returned_exactly_once() {
        let position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        let original = position.legal_moves();
        let mut scratch = original.clone();
        let mut picker = MovePicker::new(&mut scratch, Some(original.as_slice()[3]));
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
