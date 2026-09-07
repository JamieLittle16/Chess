#!/usr/bin/env python3
"""Apply verified null-move pruning v3 over the exact current production search.

This patch deliberately preserves the accepted production negamax rather than replacing it.
It adds a reversible synthetic null transition, isolates synthetic search state from rule-draw/TT/
killer/RFP side effects, and layers a TT-informed, zugzwang-aware null policy onto the existing
RFP + PVS + LMR v3 + late-quiet-futility stack.
"""

from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# chess-core: reversible synthetic null transition.
# ---------------------------------------------------------------------------
reversible_path = Path("crates/chess-core/src/reversible.rs")
reversible = reversible_path.read_text()
reversible = replace_once(
    reversible,
    "pub struct Undo {\n"
    "    captured: Option<CapturedPiece>,\n"
    "    castling: CastlingRights,\n"
    "    en_passant: Option<Square>,\n"
    "    halfmove_clock: u16,\n"
    "    fullmove_number: u16,\n"
    "}\n",
    "pub struct Undo {\n"
    "    captured: Option<CapturedPiece>,\n"
    "    castling: CastlingRights,\n"
    "    en_passant: Option<Square>,\n"
    "    halfmove_clock: u16,\n"
    "    fullmove_number: u16,\n"
    "}\n\n"
    "/// Fixed-size state destroyed by one synthetic null transition used only by search.\n"
    "#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
    "pub struct NullUndo {\n"
    "    en_passant: Option<Square>,\n"
    "}\n",
    "NullUndo definition",
)
reversible = replace_once(
    reversible,
    "    /// Reverse exactly one preceding [`Position::make_move`] call.\n"
    "    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {",
    "    /// Apply one synthetic null transition for search pruning.\n"
    "    ///\n"
    "    /// A null transition is not a legal chess move and must never enter game/repetition\n"
    "    /// history. Castling rights and clocks are preserved, en-passant availability is cleared,\n"
    "    /// and side-to-move is flipped through the canonical Zobrist-aware setters.\n"
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
    "    #[test]\n"
    "    fn reversible_transition_matches_reference_across_special_positions() {",
    "    #[test]\n"
    "    fn null_transition_round_trips_ep_clocks_side_and_zobrist() {\n"
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
    "    #[test]\n"
    "    fn reversible_transition_matches_reference_across_special_positions() {",
    "null transition regression",
)
reversible_path.write_text(reversible)

core_lib_path = Path("crates/chess-core/src/lib.rs")
core_lib = core_lib_path.read_text()
core_lib = replace_once(
    core_lib,
    "pub use reversible::Undo;",
    "pub use reversible::{NullUndo, Undo};",
    "NullUndo export",
)
core_lib_path.write_text(core_lib)


# ---------------------------------------------------------------------------
# chess-search: surgically add isolated, verified NMP without replacing negamax.
# ---------------------------------------------------------------------------
search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(
    search,
    "const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;\n"
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;\n",
    "const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;\n"
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;\n"
    "const NMP_MIN_DEPTH: u8 = 5;\n"
    "const NMP_MIN_STATIC_MARGIN: i32 = 40;\n"
    "const NMP_VERIFY_MARGIN: i32 = 160;\n",
    "NMP constants",
)
search = replace_once(
    search,
    "    path_keys: [u64; MAX_SEARCH_PLY],\n"
    "    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n"
    "}",
    "    path_keys: [u64; MAX_SEARCH_PLY],\n"
    "    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n"
    "    synthetic_null: bool,\n"
    "    null_forbidden: bool,\n"
    "}",
    "Searcher synthetic state",
)
search = replace_once(
    search,
    "            path_keys: [0; MAX_SEARCH_PLY],\n"
    "            killers: [[None; 2]; MAX_SEARCH_PLY],\n"
    "        }",
    "            path_keys: [0; MAX_SEARCH_PLY],\n"
    "            killers: [[None; 2]; MAX_SEARCH_PLY],\n"
    "            synthetic_null: false,\n"
    "            null_forbidden: false,\n"
    "        }",
    "Searcher initialization",
)
search = replace_once(
    search,
    "        self.nodes = 1;\n"
    "        self.tt_hits = 0;\n"
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n",
    "        self.nodes = 1;\n"
    "        self.tt_hits = 0;\n"
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n"
    "        self.synthetic_null = false;\n"
    "        self.null_forbidden = false;\n",
    "fixed-depth synthetic reset",
)
search = replace_once(
    search,
    "        self.nodes = 0;\n"
    "        self.tt_hits = 0;\n"
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n",
    "        self.nodes = 0;\n"
    "        self.tt_hits = 0;\n"
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n"
    "        self.synthetic_null = false;\n"
    "        self.null_forbidden = false;\n",
    "iterative synthetic reset",
)
search = replace_once(
    search,
    "        let repetition_key = position.repetition_key().raw();\n"
    "        if is_rule_draw(\n"
    "            position,\n"
    "            repetition_key,\n"
    "            prior_history,\n"
    "            &self.path_keys[..path_len],\n"
    "        ) {",
    "        let repetition_key = position.repetition_key().raw();\n"
    "        if !self.synthetic_null\n"
    "            && is_rule_draw(\n"
    "                position,\n"
    "                repetition_key,\n"
    "                prior_history,\n"
    "                &self.path_keys[..path_len],\n"
    "            )\n"
    "        {",
    "negamax synthetic draw isolation",
)
search = replace_once(
    search,
    "        let key = position.zobrist_key().raw();\n"
    "        let alpha_original = alpha;\n"
    "        let table_entry = self.probe(key);\n",
    "        let key = position.zobrist_key().raw();\n"
    "        let alpha_original = alpha;\n"
    "        let table_entry = if self.synthetic_null {\n"
    "            None\n"
    "        } else {\n"
    "            self.probe(key)\n"
    "        };\n",
    "synthetic TT probe isolation",
)
search = replace_once(
    search,
    "        let pruning_eligible = depth <= 3\n"
    "            && null_window\n",
    "        let pruning_eligible = !self.synthetic_null\n"
    "            && depth <= 3\n"
    "            && null_window\n",
    "synthetic RFP isolation",
)
search = replace_once(
    search,
    "        if let Some(static_eval) = pruning_static_eval {\n"
    "            let margin = 120 * i32::from(depth);\n"
    "            if static_eval.saturating_sub(margin) >= beta {\n"
    "                return Some(static_eval);\n"
    "            }\n"
    "        }\n\n"
    "        let moves = generate_legal_moves_mut(position);",
    "        if let Some(static_eval) = pruning_static_eval {\n"
    "            let margin = 120 * i32::from(depth);\n"
    "            if static_eval.saturating_sub(margin) >= beta {\n"
    "                return Some(static_eval);\n"
    "            }\n"
    "        }\n\n"
    "        // Verified null-move pruning v3. Unlike the rejected v1/v2 policies, this gate uses\n"
    "        // TT confidence and an explicit low-material zugzwang-risk profile. Deep R=4 is only\n"
    "        // available with both a large static margin and supporting TT evidence. Risky, R=4,\n"
    "        // and low-confidence fail-highs are verified on the real position with null disabled.\n"
    "        if !self.synthetic_null\n"
    "            && !self.null_forbidden\n"
    "            && depth >= NMP_MIN_DEPTH\n"
    "            && null_window\n"
    "            && !in_check\n"
    "            && beta.abs() < MATE_TT_THRESHOLD\n"
    "        {\n"
    "            let profile = null_move_profile(position);\n"
    "            if profile.allow {\n"
    "                let static_eval = evaluate(position);\n"
    "                let static_margin = static_eval.saturating_sub(beta);\n"
    "                let tt_support = null_move_tt_support(table_entry, depth, beta, ply);\n"
    "                let tt_contrary = null_move_tt_contrary(table_entry, depth, beta, ply);\n"
    "                if !tt_contrary\n"
    "                    && (static_margin >= NMP_MIN_STATIC_MARGIN\n"
    "                        || (tt_support && static_margin >= 0))\n"
    "                    && has_legal_move_mut(position)\n"
    "                {\n"
    "                    let reduction =\n"
    "                        null_move_reduction(depth, static_margin, tt_support, profile);\n"
    "                    let null_depth = depth.saturating_sub(1 + reduction);\n"
    "                    let undo = position.make_null_move();\n"
    "                    let previous_synthetic = self.synthetic_null;\n"
    "                    self.synthetic_null = true;\n"
    "                    let null_child = self.negamax(\n"
    "                        position,\n"
    "                        prior_history,\n"
    "                        null_depth,\n"
    "                        -beta,\n"
    "                        -beta + 1,\n"
    "                        ply + 1,\n"
    "                        path_len,\n"
    "                        control,\n"
    "                    );\n"
    "                    self.synthetic_null = previous_synthetic;\n"
    "                    position.unmake_null_move(undo);\n"
    "                    let null_score = -null_child?;\n"
    "                    if null_score >= beta {\n"
    "                        let must_verify = profile.zugzwang_risk\n"
    "                            || reduction >= 4\n"
    "                            || (!tt_support && static_margin < NMP_VERIFY_MARGIN);\n"
    "                        if must_verify {\n"
    "                            let previous_forbidden = self.null_forbidden;\n"
    "                            self.null_forbidden = true;\n"
    "                            let verification = self.negamax(\n"
    "                                position,\n"
    "                                prior_history,\n"
    "                                depth.saturating_sub(reduction),\n"
    "                                beta - 1,\n"
    "                                beta,\n"
    "                                ply,\n"
    "                                path_len,\n"
    "                                control,\n"
    "                            );\n"
    "                            self.null_forbidden = previous_forbidden;\n"
    "                            let verification_score = verification?;\n"
    "                            if verification_score >= beta {\n"
    "                                return Some(verification_score);\n"
    "                            }\n"
    "                        } else {\n"
    "                            return Some(beta);\n"
    "                        }\n"
    "                    }\n"
    "                }\n"
    "            }\n"
    "        }\n\n"
    "        let moves = generate_legal_moves_mut(position);",
    "NMP v3 policy insertion",
)
search = replace_once(
    search,
    "        let moves = generate_legal_moves_mut(position);\n"
    "        if moves.is_empty() {\n"
    "            let score = terminal_score(position, ply);\n"
    "            self.table\n"
    "                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);\n"
    "            return Some(score);\n"
    "        }\n\n"
    "        debug_assert!(path_len < MAX_SEARCH_PLY);",
    "        let moves = generate_legal_moves_mut(position);\n"
    "        if moves.is_empty() {\n"
    "            let score = terminal_score(position, ply);\n"
    "            if !self.synthetic_null {\n"
    "                self.table\n"
    "                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);\n"
    "            }\n"
    "            return Some(score);\n"
    "        }\n\n"
    "        debug_assert!(path_len < MAX_SEARCH_PLY);",
    "synthetic terminal TT isolation",
)
search = replace_once(
    search,
    "        let mut moves = moves;\n"
    "        let killers = self.killers[usize::from(ply)];\n"
    "        let mut picker = MovePicker::new(&mut moves, hint, killers);",
    "        let mut moves = moves;\n"
    "        let killers = if self.synthetic_null {\n"
    "            [None; 2]\n"
    "        } else {\n"
    "            self.killers[usize::from(ply)]\n"
    "        };\n"
    "        let mut picker = MovePicker::new(&mut moves, hint, killers);",
    "synthetic killer ordering isolation",
)
search = replace_once(
    search,
    "            if alpha >= beta {\n"
    "                if !mv.kind().is_capture() && !mv.kind().is_promotion() {\n"
    "                    let killers = &mut self.killers[usize::from(ply)];",
    "            if alpha >= beta {\n"
    "                if !self.synthetic_null\n"
    "                    && !mv.kind().is_capture()\n"
    "                    && !mv.kind().is_promotion()\n"
    "                {\n"
    "                    let killers = &mut self.killers[usize::from(ply)];",
    "synthetic killer update isolation",
)
search = replace_once(
    search,
    "        self.table\n"
    "            .store(key, depth, score_to_tt(best, ply), bound, best_move);\n"
    "        Some(best)\n"
    "    }\n\n"
    "    fn fallback_result",
    "        if !self.synthetic_null {\n"
    "            self.table\n"
    "                .store(key, depth, score_to_tt(best, ply), bound, best_move);\n"
    "        }\n"
    "        Some(best)\n"
    "    }\n\n"
    "    fn fallback_result",
    "synthetic final TT isolation",
)
search = replace_once(
    search,
    "fn has_reverse_futility_material(position: &Position) -> bool {",
    "#[derive(Clone, Copy, Debug, PartialEq, Eq)]\n"
    "struct NullMoveProfile {\n"
    "    allow: bool,\n"
    "    zugzwang_risk: bool,\n"
    "}\n\n"
    "fn null_move_profile(position: &Position) -> NullMoveProfile {\n"
    "    let us = position.side_to_move();\n"
    "    let queens = position.pieces(us, PieceKind::Queen).count();\n"
    "    let rooks = position.pieces(us, PieceKind::Rook).count();\n"
    "    let minors = (position.pieces(us, PieceKind::Knight)\n"
    "        | position.pieces(us, PieceKind::Bishop))\n"
    "    .count();\n"
    "    let allow = queens > 0 || rooks > 0 || minors >= 2;\n"
    "    let zugzwang_risk = (queens == 0 && rooks == 0 && minors <= 2)\n"
    "        || (queens == 0 && rooks == 1 && minors == 0);\n"
    "    NullMoveProfile {\n"
    "        allow,\n"
    "        zugzwang_risk,\n"
    "    }\n"
    "}\n\n"
    "fn null_move_tt_support(\n"
    "    entry: Option<TtEntry>,\n"
    "    depth: u8,\n"
    "    beta: i32,\n"
    "    ply: u16,\n"
    ") -> bool {\n"
    "    entry.is_some_and(|entry| {\n"
    "        entry.depth.saturating_add(2) >= depth\n"
    "            && matches!(entry.bound, Bound::Exact | Bound::Lower)\n"
    "            && score_from_tt(entry.score, ply) >= beta\n"
    "    })\n"
    "}\n\n"
    "fn null_move_tt_contrary(\n"
    "    entry: Option<TtEntry>,\n"
    "    depth: u8,\n"
    "    beta: i32,\n"
    "    ply: u16,\n"
    ") -> bool {\n"
    "    entry.is_some_and(|entry| {\n"
    "        entry.depth.saturating_add(1) >= depth\n"
    "            && matches!(entry.bound, Bound::Exact | Bound::Upper)\n"
    "            && score_from_tt(entry.score, ply) < beta\n"
    "    })\n"
    "}\n\n"
    "fn null_move_reduction(\n"
    "    depth: u8,\n"
    "    static_margin: i32,\n"
    "    tt_support: bool,\n"
    "    profile: NullMoveProfile,\n"
    ") -> u8 {\n"
    "    let mut reduction = 2;\n"
    "    if depth >= 7 && (tt_support || static_margin >= 180) {\n"
    "        reduction = 3;\n"
    "    }\n"
    "    if depth >= 10 && tt_support && static_margin >= 300 && !profile.zugzwang_risk {\n"
    "        reduction = 4;\n"
    "    }\n"
    "    reduction.min(depth.saturating_sub(2))\n"
    "}\n\n"
    "fn has_reverse_futility_material(position: &Position) -> bool {",
    "NMP helper functions",
)
search = replace_once(
    search,
    "    #[test]\n"
    "    fn mate_scores_are_normalized_across_transposition_ply() {",
    "    #[test]\n"
    "    fn null_move_profile_excludes_zugzwang_prone_material() {\n"
    "        let pawns = Position::from_fen(\"8/8/8/8/8/7k/P7/K7 w - - 0 1\")\n"
    "            .expect(\"valid pawn ending\");\n"
    "        assert!(!super::null_move_profile(&pawns).allow);\n\n"
    "        let bishop = Position::from_fen(\"8/8/8/8/8/7k/B7/K7 w - - 0 1\")\n"
    "            .expect(\"valid minor ending\");\n"
    "        assert!(!super::null_move_profile(&bishop).allow);\n\n"
    "        let rook = Position::from_fen(\"8/8/8/8/8/7k/R7/K7 w - - 0 1\")\n"
    "            .expect(\"valid rook ending\");\n"
    "        let rook_profile = super::null_move_profile(&rook);\n"
    "        assert!(rook_profile.allow);\n"
    "        assert!(rook_profile.zugzwang_risk);\n\n"
    "        let opening = super::null_move_profile(&Position::startpos());\n"
    "        assert!(opening.allow);\n"
    "        assert!(!opening.zugzwang_risk);\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn null_move_v3_reduction_reserves_r4_for_high_confidence() {\n"
    "        let safe = super::NullMoveProfile {\n"
    "            allow: true,\n"
    "            zugzwang_risk: false,\n"
    "        };\n"
    "        let risky = super::NullMoveProfile {\n"
    "            allow: true,\n"
    "            zugzwang_risk: true,\n"
    "        };\n"
    "        assert_eq!(super::null_move_reduction(5, 80, false, safe), 2);\n"
    "        assert_eq!(super::null_move_reduction(8, 200, false, safe), 3);\n"
    "        assert_eq!(super::null_move_reduction(10, 320, true, safe), 4);\n"
    "        assert_eq!(super::null_move_reduction(10, 320, true, risky), 3);\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn synthetic_null_subtree_does_not_claim_real_threefold() {\n"
    "        let mut root = Position::from_fen(\"7k/8/8/8/8/8/6Q1/K7 w - - 0 1\")\n"
    "            .expect(\"valid FEN\");\n"
    "        let original = root.clone();\n"
    "        let key = root.repetition_key().raw();\n"
    "        let mut searcher = Searcher::default();\n"
    "        searcher.synthetic_null = true;\n"
    "        let score = searcher\n"
    "            .negamax(&mut root, &[key, key], 1, -32_000, 32_000, 0, 0, &super::NeverStop)\n"
    "            .expect(\"synthetic search completes\");\n"
    "        searcher.synthetic_null = false;\n"
    "        assert!(score > 0);\n"
    "        assert_eq!(root, original);\n"
    "    }\n\n"
    "    #[test]\n"
    "    fn mate_scores_are_normalized_across_transposition_ply() {",
    "NMP policy regressions",
)
search_path.write_text(search)


# ---------------------------------------------------------------------------
# qsearch: synthetic null subtrees must not inherit real repetition/50-move claims.
# ---------------------------------------------------------------------------
q_path = Path("crates/chess-search/src/quiescence.rs")
qsearch = q_path.read_text()
qsearch = replace_once(
    qsearch,
    "        let repetition_key = position.repetition_key().raw();\n"
    "        if is_rule_draw(\n"
    "            position,\n"
    "            repetition_key,\n"
    "            prior_history,\n"
    "            &self.path_keys[..path_len],\n"
    "        ) {",
    "        let repetition_key = position.repetition_key().raw();\n"
    "        if !self.synthetic_null\n"
    "            && is_rule_draw(\n"
    "                position,\n"
    "                repetition_key,\n"
    "                prior_history,\n"
    "                &self.path_keys[..path_len],\n"
    "            )\n"
    "        {",
    "qsearch synthetic draw isolation",
)
q_path.write_text(qsearch)
