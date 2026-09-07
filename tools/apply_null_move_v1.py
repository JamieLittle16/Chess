#!/usr/bin/env python3
"""Apply a conservative, draw-safe null-move pruning prototype."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Core: reversible synthetic null transition. Clocks are deliberately preserved; en-passant is
# cleared and side-to-move is toggled through the canonical Zobrist-aware setters.
reversible_path = Path("crates/chess-core/src/reversible.rs")
reversible = reversible_path.read_text()
reversible = replace_once(
    reversible,
    "pub struct Undo {\n    captured: Option<CapturedPiece>,\n    castling: CastlingRights,\n    en_passant: Option<Square>,\n    halfmove_clock: u16,\n    fullmove_number: u16,\n}\n",
    "pub struct Undo {\n    captured: Option<CapturedPiece>,\n    castling: CastlingRights,\n    en_passant: Option<Square>,\n    halfmove_clock: u16,\n    fullmove_number: u16,\n}\n\n"
    "/// State destroyed by one synthetic null transition used only by search.\n"
    "#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
    "pub struct NullUndo {\n"
    "    en_passant: Option<Square>,\n"
    "}\n",
    "NullUndo definition",
)
reversible = replace_once(
    reversible,
    "    /// Reverse exactly one preceding [`Position::make_move`] call.\n    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {",
    "    /// Apply a synthetic null transition for search pruning.\n"
    "    ///\n"
    "    /// This is not a legal chess move and must never be appended to game history. It preserves\n"
    "    /// move clocks and castling rights, clears en-passant availability, and flips side-to-move.\n"
    "    /// Search is responsible for suppressing history-dependent draw adjudication while this\n"
    "    /// synthetic state is active.\n"
    "    #[must_use]\n"
    "    pub fn make_null_move(&mut self) -> NullUndo {\n"
    "        let undo = NullUndo {\n"
    "            en_passant: self.en_passant(),\n"
    "        };\n"
    "        let us = self.side_to_move();\n"
    "        self.set_en_passant(None);\n"
    "        self.set_side_to_move(us.opposite());\n"
    "        debug_assert!(self.structural_invariants_hold());\n"
    "        debug_assert_eq!(self.zobrist_key(), self.recomputed_zobrist_key());\n"
    "        undo\n"
    "    }\n\n"
    "    /// Reverse exactly one preceding [`Position::make_null_move`] call.\n"
    "    pub fn unmake_null_move(&mut self, undo: NullUndo) {\n"
    "        let us = self.side_to_move().opposite();\n"
    "        self.set_side_to_move(us);\n"
    "        self.set_en_passant(undo.en_passant);\n"
    "        debug_assert!(self.structural_invariants_hold());\n"
    "        debug_assert_eq!(self.zobrist_key(), self.recomputed_zobrist_key());\n"
    "    }\n\n"
    "    /// Reverse exactly one preceding [`Position::make_move`] call.\n"
    "    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {",
    "null transition methods",
)
reversible = replace_once(
    reversible,
    "    #[test]\n    fn reversible_transition_matches_reference_across_special_positions() {",
    "    #[test]\n"
    "    fn null_transition_round_trips_side_ep_clocks_and_zobrist() {\n"
    "        let mut position = Position::from_fen(\n"
    "            \"8/8/8/3pP3/8/8/8/K6k w - d6 73 42\",\n"
    "        )\n"
    "        .expect(\"test FEN\");\n"
    "        let original = position.clone();\n"
    "        let undo = position.make_null_move();\n"
    "        assert_ne!(position.side_to_move(), original.side_to_move());\n"
    "        assert_eq!(position.en_passant(), None);\n"
    "        assert_eq!(position.halfmove_clock(), original.halfmove_clock());\n"
    "        assert_eq!(position.fullmove_number(), original.fullmove_number());\n"
    "        assert_eq!(position.zobrist_key(), position.recomputed_zobrist_key());\n"
    "        position.unmake_null_move(undo);\n"
    "        assert_eq!(position, original);\n"
    "    }\n\n"
    "    #[test]\n    fn reversible_transition_matches_reference_across_special_positions() {",
    "null transition test",
)
reversible_path.write_text(reversible)

core_lib_path = Path("crates/chess-core/src/lib.rs")
core_lib = core_lib_path.read_text()
core_lib = replace_once(core_lib, "pub use reversible::Undo;", "pub use reversible::{NullUndo, Undo};", "core export")
core_lib_path.write_text(core_lib)

# Search: normal nodes retain existing draw/TT semantics. Synthetic null subtrees disable both
# history-dependent draw adjudication and TT probe/store, preventing context-dependent values from
# escaping into real search. They also cannot perform another null move or record killers.
search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(
    search,
    "use chess_core::{ChessMove, Position, generate_legal_moves_mut};",
    "use chess_core::{ChessMove, PieceKind, Position, generate_legal_moves_mut};",
    "search imports",
)
search = replace_once(
    search,
    "impl SearchControl for NeverStop {\n    fn should_stop(&self, _nodes: u64) -> bool {\n        false\n    }\n}\n",
    "impl SearchControl for NeverStop {\n    fn should_stop(&self, _nodes: u64) -> bool {\n        false\n    }\n}\n\n"
    "#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
    "struct SearchMode {\n"
    "    synthetic: bool,\n"
    "    allow_null: bool,\n"
    "}\n\n"
    "impl SearchMode {\n"
    "    const NORMAL: Self = Self {\n"
    "        synthetic: false,\n"
    "        allow_null: true,\n"
    "    };\n"
    "    const NULL_SUBTREE: Self = Self {\n"
    "        synthetic: true,\n"
    "        allow_null: false,\n"
    "    };\n"
    "}\n",
    "SearchMode",
)

start = search.index("    #[allow(clippy::too_many_arguments)]\n    fn negamax<C: SearchControl>(")
end = search.index("    fn fallback_result", start)
new_negamax = r'''    #[allow(clippy::too_many_arguments)]
    fn negamax<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
        control: &C,
    ) -> Option<i32> {
        self.negamax_mode(
            position,
            prior_history,
            depth,
            alpha,
            beta,
            ply,
            path_len,
            control,
            SearchMode::NORMAL,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn negamax_mode<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        mut alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
        control: &C,
        mode: SearchMode,
    ) -> Option<i32> {
        self.nodes = self.nodes.saturating_add(1);
        if control.should_stop(self.nodes) {
            return None;
        }

        if depth == 0 {
            return self.quiescence_mode(
                position,
                prior_history,
                alpha,
                beta,
                ply,
                path_len,
                mode.synthetic,
                control,
            );
        }

        let repetition_key = position.repetition_key().raw();
        if !mode.synthetic
            && is_rule_draw(
                position,
                repetition_key,
                prior_history,
                &self.path_keys[..path_len],
            )
        {
            if position.is_in_check(position.side_to_move()) {
                let moves = generate_legal_moves_mut(position);
                if moves.is_empty() {
                    return Some(terminal_score(position, ply));
                }
            }
            return Some(0);
        }

        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = if mode.synthetic { None } else { self.probe(key) };

        if let Some(entry) = table_entry
            && entry.depth >= depth
        {
            let score = score_from_tt(entry.score, ply);
            match entry.bound {
                Bound::Exact => return Some(score),
                Bound::Lower if score >= beta => return Some(score),
                Bound::Upper if score <= alpha => return Some(score),
                Bound::Lower | Bound::Upper => {}
            }
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            if !mode.synthetic {
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            }
            return Some(score);
        }

        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        if mode.allow_null
            && !mode.synthetic
            && depth >= 4
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && evaluate(position) >= beta
            && has_null_move_material(position)
        {
            // R=2 and the implicit passed turn consume three nominal plies. The entire child tree is
            // synthetic: no history draws, TT reads/writes, nested nulls, or killer recording.
            let undo = position.make_null_move();
            let null_child = self.negamax_mode(
                position,
                prior_history,
                depth - 3,
                -beta,
                -beta + 1,
                ply + 1,
                path_len,
                control,
                SearchMode::NULL_SUBTREE,
            );
            position.unmake_null_move(undo);
            let null_score = -null_child?;
            if null_score >= beta {
                return Some(null_score);
            }
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best = -INFINITY;
        let mut best_move = None;

        let mut moves = moves;
        let killers = if mode.synthetic {
            [None; 2]
        } else {
            self.killers[usize::from(ply)]
        };
        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {
                self.negamax_mode(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                    mode,
                )
            } else {
                let probe = self.negamax_mode(
                    position,
                    prior_history,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                    mode,
                );
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax_mode(
                            position,
                            prior_history,
                            depth - 1,
                            -beta,
                            -alpha,
                            ply + 1,
                            path_len + 1,
                            control,
                            mode,
                        ),
                    probe => probe,
                }
            };
            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;

            if score > best {
                best = score;
                best_move = Some(mv);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
                if !mode.synthetic && !mv.kind().is_capture() && !mv.kind().is_promotion() {
                    let killers = &mut self.killers[usize::from(ply)];
                    if killers[0] != Some(mv) {
                        killers[1] = killers[0];
                        killers[0] = Some(mv);
                    }
                }
                break;
            }
        }

        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };
        if !mode.synthetic {
            self.table
                .store(key, depth, score_to_tt(best, ply), bound, best_move);
        }
        Some(best)
    }

'''
search = search[:start] + new_negamax + search[end:]
search = replace_once(
    search,
    "fn terminal_score(position: &Position, ply: u16) -> i32 {",
    "fn has_null_move_material(position: &Position) -> bool {\n"
    "    let us = position.side_to_move();\n"
    "    let heavy = !(position.pieces(us, PieceKind::Rook) | position.pieces(us, PieceKind::Queen))\n"
    "        .is_empty();\n"
    "    let minors = (position.pieces(us, PieceKind::Knight) | position.pieces(us, PieceKind::Bishop))\n"
    "        .count();\n"
    "    heavy || minors >= 2\n"
    "}\n\n"
    "fn terminal_score(position: &Position, ply: u16) -> i32 {",
    "null material guard",
)
search_path.write_text(search)

# Quiescence: retain the normal public wrapper for tests/callers, but allow the synthetic null
# subtree to skip history-dependent rule draws all the way through the tactical horizon.
q_path = Path("crates/chess-search/src/quiescence.rs")
q = q_path.read_text()
q = replace_once(
    q,
    "        self.quiescence_inner(\n            position,\n            prior_history,\n            alpha,\n            beta,\n            ply,\n            path_len,\n            0,\n            control,\n        )",
    "        self.quiescence_mode(\n            position,\n            prior_history,\n            alpha,\n            beta,\n            ply,\n            path_len,\n            false,\n            control,\n        )",
    "normal qsearch wrapper",
)
q = replace_once(
    q,
    "    #[allow(clippy::too_many_arguments)]\n    fn quiescence_inner<C: SearchControl>(",
    "    #[allow(clippy::too_many_arguments)]\n"
    "    pub(super) fn quiescence_mode<C: SearchControl>(\n"
    "        &mut self,\n"
    "        position: &mut Position,\n"
    "        prior_history: &[u64],\n"
    "        alpha: i32,\n"
    "        beta: i32,\n"
    "        ply: u16,\n"
    "        path_len: usize,\n"
    "        synthetic: bool,\n"
    "        control: &C,\n"
    "    ) -> Option<i32> {\n"
    "        self.quiescence_inner(\n"
    "            position, prior_history, alpha, beta, ply, path_len, 0, synthetic, control,\n"
    "        )\n"
    "    }\n\n"
    "    #[allow(clippy::too_many_arguments)]\n"
    "    fn quiescence_inner<C: SearchControl>(",
    "qsearch mode wrapper",
)
q = replace_once(
    q,
    "        qply: usize,\n        control: &C,",
    "        qply: usize,\n        synthetic: bool,\n        control: &C,",
    "qsearch inner mode arg",
)
q = replace_once(
    q,
    "        if is_rule_draw(\n            position,\n            repetition_key,\n            prior_history,\n            &self.path_keys[..path_len],\n        ) {",
    "        if !synthetic\n            && is_rule_draw(\n                position,\n                repetition_key,\n                prior_history,\n                &self.path_keys[..path_len],\n            )\n        {",
    "synthetic draw suppression",
)
q = replace_once(
    q,
    "                qply + 1,\n                control,",
    "                qply + 1,\n                synthetic,\n                control,",
    "qsearch recursive propagation",
)
q = replace_once(
    q,
    "                MAX_QSEARCH_PLY,\n                &NeverStop,",
    "                MAX_QSEARCH_PLY,\n                false,\n                &NeverStop,",
    "qsearch direct test",
)
q_path.write_text(q)
