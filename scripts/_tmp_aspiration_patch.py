from pathlib import Path

path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

text = text.replace(
    "const MAX_SEARCH_PLY: usize = 256;\n",
    "const MAX_SEARCH_PLY: usize = 256;\nconst ASPIRATION_INITIAL_WINDOW: i32 = 50;\n",
    1,
)

old = """        let result = self
            .search_root(position, prior_history, depth, &NeverStop)
            .expect(\"NeverStop cannot interrupt search\");
"""
new = """        let result = self
            .search_root(
                position,
                prior_history,
                depth,
                -INFINITY,
                INFINITY,
                &NeverStop,
            )
            .expect(\"NeverStop cannot interrupt search\");
"""
if old not in text:
    raise SystemExit("search_depth root-call anchor missing")
text = text.replace(old, new, 1)

start = text.index("    pub fn iterative_deepening_controlled_with_history<C: SearchControl>(")
end = text.index("    fn search_root<C: SearchControl>(", start)
iterative = r'''    pub fn iterative_deepening_controlled_with_history<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        max_depth: u8,
        control: &C,
    ) -> SearchOutcome {
        if max_depth == 0 {
            return SearchOutcome {
                result: self.search_depth_with_history(position, prior_history, 0),
                stopped: false,
            };
        }

        #[cfg(debug_assertions)]
        let root = position.clone();

        self.nodes = 0;
        self.tt_hits = 0;
        let mut last_completed: Option<SearchResult> = None;

        for depth in 1..=max_depth {
            let previous_score = last_completed.map(|result| result.score);
            let use_aspiration = depth > 1
                && previous_score.is_some_and(|score| score.abs() < MATE_TT_THRESHOLD);
            let mut window = if use_aspiration {
                ASPIRATION_INITIAL_WINDOW
            } else {
                INFINITY
            };

            loop {
                let (alpha, beta) = if let Some(center) = previous_score
                    && window < INFINITY
                {
                    (
                        center.saturating_sub(window).max(-INFINITY),
                        center.saturating_add(window).min(INFINITY),
                    )
                } else {
                    (-INFINITY, INFINITY)
                };

                // Every aspiration retry is real root work and must count toward node limits.
                self.nodes = self.nodes.saturating_add(1);
                match self.search_root(position, prior_history, depth, alpha, beta, control) {
                    Some(mut result) => {
                        let failed_low = result.score <= alpha && alpha > -INFINITY;
                        let failed_high = result.score >= beta && beta < INFINITY;
                        if failed_low || failed_high {
                            window = window.saturating_mul(2).min(INFINITY);
                            continue;
                        }

                        result.nodes = self.nodes;
                        result.tt_hits = self.tt_hits;
                        last_completed = Some(result);
                        break;
                    }
                    None => {
                        let result = match last_completed {
                            Some(mut result) => {
                                result.nodes = self.nodes;
                                result.tt_hits = self.tt_hits;
                                result
                            }
                            None => self.fallback_result(position, prior_history),
                        };
                        #[cfg(debug_assertions)]
                        debug_assert_eq!(*position, root);
                        return SearchOutcome {
                            result,
                            stopped: true,
                        };
                    }
                }
            }
        }

        let result = last_completed.expect("positive max_depth completes at least depth one");
        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);
        SearchOutcome {
            result,
            stopped: false,
        }
    }

'''
text = text[:start] + iterative + text[end:]

start = text.index("    fn search_root<C: SearchControl>(")
end = text.index("    #[allow(clippy::too_many_arguments)]\n    fn negamax", start)
root = r'''    #[allow(clippy::too_many_arguments)]
    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        mut alpha: i32,
        beta: i32,
        control: &C,
    ) -> Option<SearchResult> {
        debug_assert!(alpha < beta);
        // Control must precede even a root TT hit; otherwise a cached result can make an
        // interruptible depth-only search ignore an already-issued UCI `stop`.
        if control.should_stop(self.nodes) {
            return None;
        }

        let repetition_key = position.repetition_key().raw();
        if is_rule_draw(position, repetition_key, prior_history, &[]) {
            let moves = generate_legal_moves_mut(position);
            let (best_move, score) = if moves.is_empty() {
                (None, terminal_score(position, 0))
            } else {
                (Some(moves[0]), 0)
            };
            return Some(self.result(best_move, score, depth));
        }

        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = self.probe(key);
        if let Some(entry) = table_entry
            && entry.depth >= depth
        {
            let score = score_from_tt(entry.score, 0);
            match entry.bound {
                Bound::Exact => {
                    return Some(SearchResult {
                        best_move: entry.best_move,
                        score,
                        depth,
                        nodes: self.nodes,
                        tt_hits: self.tt_hits,
                    });
                }
                Bound::Lower if score >= beta => {
                    return Some(self.result(entry.best_move, score, depth));
                }
                Bound::Upper if score <= alpha => {
                    return Some(self.result(entry.best_move, score, depth));
                }
                Bound::Lower | Bound::Upper => {}
            }
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, 0);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return Some(self.result(None, score, depth));
        }

        if depth == 0 {
            let score = evaluate(position);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return Some(self.result(None, score, depth));
        }

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;
        let mut best_score = -INFINITY;
        self.path_keys[0] = repetition_key;

        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    1,
                    1,
                    control,
                )
            } else {
                // Later root moves first get a null-window probe. Good ordering should make most
                // fail low; only genuine alpha improvements inside beta need a full re-search.
                let probe = self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    1,
                    1,
                    control,
                );
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            depth - 1,
                            -beta,
                            -alpha,
                            1,
                            1,
                            control,
                        ),
                    probe => probe,
                }
            };
            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;

            if score > best_score {
                best_score = score;
                best_move = Some(mv);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
                break;
            }
        }

        let bound = if best_score <= alpha_original {
            Bound::Upper
        } else if best_score >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };
        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            bound,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))
    }

'''
text = text[:start] + root + text[end:]

path.write_text(text)
