use super::*;

impl Searcher {
    /// Stabilise a nominal leaf by resolving forcing tactical continuations.
    ///
    /// Outside check we use the ordinary static evaluation as stand-pat and search only captures
    /// and promotions. In check there is no stand-pat: every legal evasion is searched. The first
    /// quiescence implementation deliberately has no TT, SEE, delta pruning or speculative
    /// reductions; it exists as a transparent tactical-correctness baseline.
    #[allow(clippy::too_many_arguments)]
    pub(super) fn quiescence<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        mut alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
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
            // Checkmate takes precedence over a claimable draw. In non-check positions the draw
            // score is already the correct terminal value, including stalemate.
            if position.is_in_check(position.side_to_move()) {
                let moves = generate_legal_moves_mut(position);
                if moves.is_empty() {
                    return Some(terminal_score(position, ply));
                }
            }
            return Some(0);
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            return Some(terminal_score(position, ply));
        }

        let in_check = position.is_in_check(position.side_to_move());
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

        // This is a robustness ceiling rather than a normal search boundary. Captures, promotions,
        // repetition and the fifty-move rule make reaching it extraordinarily unlikely, but a
        // malformed or adversarial position must never index beyond the fixed search-history stack.
        if path_len >= MAX_SEARCH_PLY {
            return Some(evaluate(position));
        }
        self.path_keys[path_len] = repetition_key;

        for mv in OrderedMoves::new(&moves, None) {
            let tactical = mv.kind().is_capture() || mv.kind().is_promotion();
            if !in_check && !tactical {
                continue;
            }

            let undo = position.make_move(mv);
            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence(
                position,
                prior_history,
                -beta,
                -alpha,
                ply + 1,
                path_len + 1,
                control,
            );
            position.unmake_move(mv, undo);
            let score = -child?;

            best = best.max(score);
            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }

        Some(best)
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Position, Square};

    use super::*;

    #[test]
    fn poisoned_capture_is_rejected_at_the_horizon() {
        // Qxd7 wins a pawn according to a static depth-one leaf, but ...Rxd7 loses the queen.
        // Quiescence must see the recapture and prefer a quiet move that keeps White's material
        // advantage instead.
        let root =
            Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
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
        assert!(result.score >= 250, "quiet queen moves retain the material edge");
    }

    #[test]
    fn quiescence_restores_position_exactly() {
        let mut position =
            Position::from_fen("3r3k/3p4/8/8/8/8/8/K2Q4 w - - 0 1").expect("valid FEN");
        let original = position.clone();
        let mut searcher = Searcher::default();
        searcher.nodes = 1;
        let _ = searcher
            .quiescence(&mut position, &[], -INFINITY, INFINITY, 0, 0, &NeverStop)
            .expect("uncontrolled quiescence completes");
        assert_eq!(position, original);
    }

    #[test]
    fn in_check_does_not_use_stand_pat() {
        // White is in rook check and materially ahead. The king has quiet evasions; returning the
        // raw stand-pat without searching them would violate quiescence semantics.
        let mut position =
            Position::from_fen("4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1").expect("valid FEN");
        assert!(position.is_in_check(position.side_to_move()));
        let original = position.clone();
        let mut searcher = Searcher::default();
        searcher.nodes = 1;
        let score = searcher
            .quiescence(&mut position, &[], -INFINITY, INFINITY, 0, 0, &NeverStop)
            .expect("uncontrolled quiescence completes");
        assert!(score > -INFINITY);
        assert!(searcher.nodes > 1, "at least one legal evasion was searched");
        assert_eq!(position, original);
    }
}
