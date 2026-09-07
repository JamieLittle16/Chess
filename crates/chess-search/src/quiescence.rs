use chess_core::{MoveKind, PieceKind, generate_legal_tactical_moves_mut};

use super::*;
use crate::see::see;

const MAX_QSEARCH_PLY: usize = 4;
const QSEARCH_DELTA_MARGIN: i32 = 140;
const QSEARCH_BAD_CAPTURE_THRESHOLD: i32 = -80;
const QSEARCH_BAD_CAPTURE_ALPHA_MARGIN: i32 = 90;
const QSEARCH_VALUES: [i32; 6] = [100, 320, 330, 500, 900, 0];

impl Searcher {
    /// Stabilise a nominal leaf by resolving forcing tactical continuations.
    ///
    /// Outside check we use static evaluation as stand-pat and generate captures/promotions only.
    /// Conservative qsearch-v2 selectivity may discard a non-checking, non-promoting capture when
    /// either its maximum immediate material swing cannot reach alpha or a legality-aware SEE says
    /// it is clearly losing while stand-pat is already well below alpha. Checks, promotions and all
    /// check evasions remain fully searched.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn quiescence<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
        control: &C,
    ) -> Option<i32> {
        self.quiescence_inner(
            position,
            prior_history,
            alpha,
            beta,
            ply,
            path_len,
            0,
            control,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn quiescence_inner<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        mut alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
        qply: usize,
        control: &C,
    ) -> Option<i32> {
        if control.should_stop(self.nodes) {
            return None;
        }

        let repetition_key = position.repetition_key().raw();
        if is_rule_draw(
            position,
            repetition_key,
            prior_history,
            &self.path_keys[..path_len],
        ) {
            if position.is_in_check(position.side_to_move()) {
                let moves = generate_legal_moves_mut(position);
                if moves.is_empty() {
                    return Some(terminal_score(position, ply));
                }
            }
            return Some(0);
        }

        let in_check = position.is_in_check(position.side_to_move());
        let moves = if in_check {
            generate_legal_moves_mut(position)
        } else {
            generate_legal_tactical_moves_mut(position)
        };

        if in_check && moves.is_empty() {
            return Some(terminal_score(position, ply));
        }

        if !in_check && moves.is_empty() {
            if generate_legal_moves_mut(position).is_empty() {
                return Some(terminal_score(position, ply));
            }
            return Some(evaluate(position));
        }

        if qply >= MAX_QSEARCH_PLY {
            return Some(evaluate(position));
        }

        let mut best = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };

        if !in_check {
            if best >= beta {
                return Some(best);
            }
            alpha = alpha.max(best);
        }

        if path_len >= MAX_SEARCH_PLY {
            return Some(evaluate(position));
        }
        self.path_keys[path_len] = repetition_key;

        let us = position.side_to_move();
        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        while let Some(mv) = picker.next(position, &self.history, us) {
            let alpha_before_move = alpha;
            let capture = mv.kind().is_capture();
            let promotion = mv.kind().is_promotion();
            let exchange = (!in_check && capture).then(|| see(position, mv));
            let optimistic = if !in_check && capture && !promotion {
                best.saturating_add(tactical_gain_bound(position, mv))
                    .saturating_add(QSEARCH_DELTA_MARGIN)
            } else {
                INFINITY
            };

            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());

            let delta_prune =
                !in_check && capture && !promotion && !gives_check && optimistic <= alpha;
            let bad_capture_prune = !in_check
                && capture
                && !promotion
                && !gives_check
                && qply > 0
                && exchange.is_some_and(|value| value < QSEARCH_BAD_CAPTURE_THRESHOLD)
                && best.saturating_add(QSEARCH_BAD_CAPTURE_ALPHA_MARGIN) <= alpha;
            if delta_prune || bad_capture_prune {
                position.unmake_move(mv, undo);
                continue;
            }

            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence_inner(
                position,
                prior_history,
                -beta,
                -alpha,
                ply + 1,
                path_len + 1,
                qply + 1,
                control,
            );
            position.unmake_move(mv, undo);
            let score = -child?;

            best = best.max(score);
            alpha = alpha.max(score);
            if alpha >= beta {
                if capture {
                    self.history.reward_capture(position, mv, 2);
                }
                break;
            }
            if capture && score <= alpha_before_move {
                self.history.penalize_capture(position, mv, 1);
            }
        }

        Some(best)
    }
}

fn tactical_gain_bound(position: &Position, mv: ChessMove) -> i32 {
    let captured = if mv.kind() == MoveKind::EnPassant {
        QSEARCH_VALUES[PieceKind::Pawn.index()]
    } else {
        position
            .piece_at(mv.to())
            .map_or(0, |piece| QSEARCH_VALUES[piece.kind().index()])
    };
    let promotion = mv.kind().promotion_piece().map_or(0, |kind| {
        QSEARCH_VALUES[kind.index()] - QSEARCH_VALUES[PieceKind::Pawn.index()]
    });
    captured.saturating_add(promotion)
}

#[cfg(test)]
mod tests {
    use chess_core::{Position, Square};

    use super::*;

    #[test]
    fn poisoned_capture_is_rejected_at_the_horizon() {
        let root = Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
        let d1 = Square::from_file_rank(3, 0).expect("d1");
        let d7 = Square::from_file_rank(3, 6).expect("d7");
        let poisoned = root
            .legal_moves()
            .as_slice()
            .iter()
            .copied()
            .find(|mv| mv.from() == d1 && mv.to() == d7)
            .expect("Qxd7 is legal");

        let result = search(&root, 1);
        assert_ne!(result.best_move, Some(poisoned));
        assert!(
            result.score >= 250,
            "quiet queen moves retain the material edge"
        );
    }

    #[test]
    fn quiescence_restores_position_exactly() {
        let mut position =
            Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let _ = searcher
            .quiescence(&mut position, &[], -INFINITY, INFINITY, 0, 0, &NeverStop)
            .expect("uncontrolled quiescence completes");
        assert_eq!(position, original);
    }

    #[test]
    fn in_check_does_not_use_stand_pat() {
        let mut position =
            Position::from_fen("4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1").expect("valid FEN");
        assert!(position.is_in_check(position.side_to_move()));
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence(&mut position, &[], -INFINITY, INFINITY, 0, 0, &NeverStop)
            .expect("uncontrolled quiescence completes");
        assert!(score > -INFINITY);
        assert!(
            searcher.nodes > 1,
            "at least one legal evasion was searched"
        );
        assert_eq!(position, original);
    }

    #[test]
    fn qsearch_local_ceiling_is_bounded_and_restores_position() {
        let mut position =
            Position::from_fen("4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1").expect("valid FEN");
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence_inner(
                &mut position,
                &[],
                -INFINITY,
                INFINITY,
                23,
                23,
                MAX_QSEARCH_PLY,
                &NeverStop,
            )
            .expect("bounded quiescence completes");
        assert_eq!(score, evaluate(&position));
        assert_eq!(searcher.nodes, 1);
        assert_eq!(position, original);
    }

    #[test]
    fn quiet_stable_leaf_does_not_need_tactical_moves() {
        let mut position = Position::startpos();
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence(&mut position, &[], -INFINITY, INFINITY, 0, 0, &NeverStop)
            .expect("quiet quiescence completes");
        assert_eq!(score, evaluate(&position));
        assert_eq!(searcher.nodes, 1);
        assert_eq!(position, original);
    }

    #[test]
    fn tactical_gain_bound_handles_en_passant_and_capture_values() {
        let ep = Position::from_fen("k7/8/8/4KPp1/8/8/8/8 w - g6 0 1").expect("valid FEN");
        let mv = ep
            .legal_moves()
            .iter()
            .copied()
            .find(|mv| mv.kind() == MoveKind::EnPassant)
            .expect("en-passant is legal");
        assert_eq!(tactical_gain_bound(&ep, mv), 100);
    }
}
