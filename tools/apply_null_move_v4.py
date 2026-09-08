#!/usr/bin/env python3
"""Apply draw-safe, Gestalt-gated verified null-move pruning v4 over V14 production.

This deliberately reuses the proven reversible synthetic-null idea without importing any old
search policy. V4 activates only when the mature Gestalt evaluator is loaded, isolates synthetic
subtrees from rule-draw/TT/history side effects, and uses conservative dynamic reductions plus
real-position verification for low-confidence fail-highs.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# chess-core: fixed-size reversible synthetic null transition.
# ---------------------------------------------------------------------------
reversible_path = Path("crates/chess-core/src/reversible.rs")
reversible = reversible_path.read_text()
reversible = replace_once(
    reversible,
    """pub struct Undo {
    captured: Option<CapturedPiece>,
    castling: CastlingRights,
    en_passant: Option<Square>,
    halfmove_clock: u16,
    fullmove_number: u16,
}
""",
    """pub struct Undo {
    captured: Option<CapturedPiece>,
    castling: CastlingRights,
    en_passant: Option<Square>,
    halfmove_clock: u16,
    fullmove_number: u16,
}

/// Fixed-size state destroyed by one synthetic null transition used only by search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct NullUndo {
    en_passant: Option<Square>,
}
""",
    "NullUndo definition",
)
reversible = replace_once(
    reversible,
    """    /// Reverse exactly one preceding [`Position::make_move`] call.
    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {
""",
    """    /// Apply one synthetic null transition for search pruning.
    ///
    /// This is not a legal chess move and must never enter game/repetition history. Castling
    /// rights and clocks are preserved, en-passant availability is cleared, and side-to-move is
    /// flipped through the canonical Zobrist-aware setters.
    #[must_use]
    pub fn make_null_move(&mut self) -> NullUndo {
        let undo = NullUndo {
            en_passant: self.en_passant(),
        };
        let us = self.side_to_move();
        self.set_en_passant(None);
        self.set_side_to_move(us.opposite());
        debug_assert!(self.structural_invariants_hold());
        debug_assert_eq!(self.zobrist_key(), self.recomputed_zobrist_key());
        undo
    }

    /// Reverse exactly one preceding [`Position::make_null_move`] call.
    pub fn unmake_null_move(&mut self, undo: NullUndo) {
        let us = self.side_to_move().opposite();
        self.set_side_to_move(us);
        self.set_en_passant(undo.en_passant);
        debug_assert!(self.structural_invariants_hold());
        debug_assert_eq!(self.zobrist_key(), self.recomputed_zobrist_key());
    }

    /// Reverse exactly one preceding [`Position::make_move`] call.
    pub fn unmake_move(&mut self, mv: ChessMove, undo: Undo) {
""",
    "null transition methods",
)
reversible = replace_once(
    reversible,
    """    #[test]
    fn reversible_transition_matches_reference_across_special_positions() {
""",
    """    #[test]
    fn null_transition_round_trips_side_ep_clocks_and_zobrist() {
        let mut position = Position::from_fen(
            "8/8/8/3pP3/8/8/8/K6k w - d6 73 42",
        )
        .expect("test FEN");
        let original = position.clone();
        let undo = position.make_null_move();
        assert_ne!(position.side_to_move(), original.side_to_move());
        assert_eq!(position.en_passant(), None);
        assert_eq!(position.halfmove_clock(), original.halfmove_clock());
        assert_eq!(position.fullmove_number(), original.fullmove_number());
        assert_eq!(position.zobrist_key(), position.recomputed_zobrist_key());
        position.unmake_null_move(undo);
        assert_eq!(position, original);
    }

    #[test]
    fn reversible_transition_matches_reference_across_special_positions() {
""",
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
# chess-search: surgically layer NMP over V14 without replacing Search-v2.
# ---------------------------------------------------------------------------
search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()

search = replace_once(
    search,
    """const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;
const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;
""",
    """const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;
const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;
const NMP_MIN_DEPTH: u8 = 5;
const NMP_MIN_MARGIN: i32 = 48;
const NMP_VERIFY_MARGIN: i32 = 144;
""",
    "NMP constants",
)
search = replace_once(
    search,
    """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    history: HistoryTables,
""",
    """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    synthetic_null: bool,
    null_forbidden: bool,
    history: HistoryTables,
""",
    "Searcher synthetic-null state",
)
search = replace_once(
    search,
    """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            history: HistoryTables::new(),
""",
    """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            synthetic_null: false,
            null_forbidden: false,
            history: HistoryTables::new(),
""",
    "Searcher synthetic-null initialization",
)
search = replace_once(
    search,
    """        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.history.clear();
""",
    """        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.synthetic_null = false;
        self.null_forbidden = false;
        self.history.clear();
""",
    "fixed-depth synthetic reset",
)
search = replace_once(
    search,
    """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.history.clear();
""",
    """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.synthetic_null = false;
        self.null_forbidden = false;
        self.history.clear();
""",
    "iterative synthetic reset",
)

search = replace_once(
    search,
    """        let repetition_key = position.repetition_key().raw();
        if is_rule_draw(
            position,
            repetition_key,
            prior_history,
            &self.path_keys[..path_len],
        ) {
""",
    """        let repetition_key = position.repetition_key().raw();
        if !self.synthetic_null
            && is_rule_draw(
                position,
                repetition_key,
                prior_history,
                &self.path_keys[..path_len],
            )
        {
""",
    "synthetic draw isolation",
)
search = replace_once(
    search,
    """        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = self.probe(key);
""",
    """        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = if self.synthetic_null {
            None
        } else {
            self.probe(key)
        };
""",
    "synthetic TT probe isolation",
)
search = replace_once(
    search,
    """        let pruning_eligible = depth <= 3
            && null_window
""",
    """        let pruning_eligible = !self.synthetic_null
            && depth <= 3
            && null_window
""",
    "synthetic shallow-pruning isolation",
)

nmp_anchor = """        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        let moves = generate_legal_moves_mut(position);
"""
nmp_block = """        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        // V15 verified NMP v4. The classical control path remains byte-for-byte in behavior:
        // null pruning activates only when the independently certified Gestalt evaluator is loaded.
        // Synthetic subtrees cannot claim history draws, touch TT state, learn history, record
        // killers, or launch another null search.
        if self.gestalt.is_some()
            && !self.synthetic_null
            && !self.null_forbidden
            && depth >= NMP_MIN_DEPTH
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
        {
            let profile = null_move_profile(position);
            if profile.allow {
                let static_eval = self.leaf_evaluate(position);
                let static_margin = static_eval.saturating_sub(beta);
                let tt_support = null_move_tt_support(table_entry, depth, beta, ply);
                let tt_contrary = null_move_tt_contrary(table_entry, depth, beta, ply);
                if !tt_contrary
                    && (static_margin >= NMP_MIN_MARGIN || (tt_support && static_margin >= 0))
                    && has_legal_move_mut(position)
                {
                    let reduction = null_move_reduction(depth, static_margin, tt_support, profile);
                    let null_depth = depth.saturating_sub(1 + reduction);
                    let undo = position.make_null_move();
                    let previous_synthetic = self.synthetic_null;
                    self.synthetic_null = true;
                    let null_child = self.negamax(
                        position,
                        prior_history,
                        null_depth,
                        -beta,
                        -beta + 1,
                        ply + 1,
                        path_len,
                        control,
                    );
                    self.synthetic_null = previous_synthetic;
                    position.unmake_null_move(undo);
                    let null_score = -null_child?;
                    if null_score >= beta {
                        let needs_verification = profile.zugzwang_risk
                            || reduction >= 4
                            || (reduction >= 3
                                && (!tt_support || static_margin < NMP_VERIFY_MARGIN));
                        if needs_verification {
                            let previous_forbidden = self.null_forbidden;
                            self.null_forbidden = true;
                            let verification = self.negamax(
                                position,
                                prior_history,
                                depth.saturating_sub(reduction),
                                beta - 1,
                                beta,
                                ply,
                                path_len,
                                control,
                            );
                            self.null_forbidden = previous_forbidden;
                            let verification_score = verification?;
                            if verification_score >= beta {
                                return Some(verification_score);
                            }
                        } else {
                            // Return only the proven bound, not the often-inflated synthetic score.
                            return Some(beta);
                        }
                    }
                }
            }
        }

        let moves = generate_legal_moves_mut(position);
"""
search = replace_once(search, nmp_anchor, nmp_block, "Gestalt NMP insertion")

search = replace_once(
    search,
    """        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }
""",
    """        if moves.is_empty() {
            let score = terminal_score(position, ply);
            if !self.synthetic_null {
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            }
            return Some(score);
        }
""",
    "synthetic terminal TT isolation",
)
search = replace_once(
    search,
    """            if quiet && null_window {
                let bonus = depth_bonus(depth);
""",
    """            if !self.synthetic_null && quiet && null_window {
                let bonus = depth_bonus(depth);
""",
    "synthetic history-learning isolation",
)
search = replace_once(
    search,
    """            if alpha >= beta {
                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
""",
    """            if alpha >= beta {
                if !self.synthetic_null && !mv.kind().is_capture() && !mv.kind().is_promotion() {
""",
    "synthetic killer isolation",
)
search = replace_once(
    search,
    """        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
        Some(best)
""",
    """        if !self.synthetic_null {
            self.table
                .store(key, depth, score_to_tt(best, ply), bound, best_move);
        }
        Some(best)
""",
    "synthetic final TT isolation",
)

helper_anchor = """fn has_reverse_futility_material(position: &Position) -> bool {
"""
helpers = """#[derive(Clone, Copy)]
struct NullMoveProfile {
    allow: bool,
    zugzwang_risk: bool,
}

fn null_move_profile(position: &Position) -> NullMoveProfile {
    let us = position.side_to_move();
    let heavy = !(position.pieces(us, PieceKind::Rook) | position.pieces(us, PieceKind::Queen))
        .is_empty();
    let minors = (position.pieces(us, PieceKind::Knight) | position.pieces(us, PieceKind::Bishop))
        .count();
    // Pawn-only and lone-minor endings are the classic zugzwang danger zone and are excluded.
    // Two-minor positions are allowed but conservatively marked for verification without heavies.
    NullMoveProfile {
        allow: heavy || minors >= 2,
        zugzwang_risk: !heavy && minors <= 2,
    }
}

fn null_move_tt_support(entry: Option<TtEntry>, depth: u8, beta: i32, ply: u16) -> bool {
    entry.is_some_and(|entry| {
        entry.depth.saturating_add(2) >= depth
            && matches!(entry.bound, Bound::Exact | Bound::Lower)
            && score_from_tt(entry.score, ply) >= beta
    })
}

fn null_move_tt_contrary(entry: Option<TtEntry>, depth: u8, beta: i32, ply: u16) -> bool {
    entry.is_some_and(|entry| {
        entry.depth.saturating_add(2) >= depth
            && matches!(entry.bound, Bound::Exact | Bound::Upper)
            && score_from_tt(entry.score, ply) < beta
    })
}

fn null_move_reduction(
    depth: u8,
    static_margin: i32,
    tt_support: bool,
    profile: NullMoveProfile,
) -> u8 {
    let mut reduction = 2;
    if depth >= 7 || static_margin >= 180 {
        reduction = 3;
    }
    if depth >= 10 && static_margin >= 300 && tt_support && !profile.zugzwang_risk {
        reduction = 4;
    }
    reduction.min(depth.saturating_sub(2))
}

fn has_reverse_futility_material(position: &Position) -> bool {
"""
search = replace_once(search, helper_anchor, helpers, "NMP helper insertion")
search_path.write_text(search)


# ---------------------------------------------------------------------------
# qsearch: synthetic null subtrees must not adjudicate history-dependent draws.
# ---------------------------------------------------------------------------
q_path = Path("crates/chess-search/src/quiescence.rs")
q = q_path.read_text()
q = replace_once(
    q,
    """        let repetition_key = position.repetition_key().raw();
        if is_rule_draw(
            position,
            repetition_key,
            prior_history,
            &self.path_keys[..path_len],
        ) {
""",
    """        let repetition_key = position.repetition_key().raw();
        if !self.synthetic_null
            && is_rule_draw(
                position,
                repetition_key,
                prior_history,
                &self.path_keys[..path_len],
            )
        {
""",
    "qsearch synthetic draw isolation",
)
q_path.write_text(q)

print("applied V15 Gestalt-gated verified null-move pruning v4")
