#!/usr/bin/env python3
"""Apply Gestalt-gated TT singular extension v1 over accepted V14 Search-v2.

The production branch stays dormant: this script materialises the research candidate only inside
qualification. The candidate uses a clean exclusion search to prove that a recent TT move is
singular before extending it by one ply. At the exclusion root the TT move is removed and that
node cannot use/store its normal TT entry; legal descendant positions may still use their own TT.
Shallow pruning, history training, killer recording, and nested singular tests stay disabled for
the entire exclusion subtree.
"""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_exact_count(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new)


path = Path("crates/chess-search/src/lib.rs")
search = path.read_text()

search = replace_once(
    search,
    """const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;
const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;
""",
    """const LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;
const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;
const SINGULAR_MIN_DEPTH: u8 = 7;
const SINGULAR_TT_DEPTH_SLACK: u8 = 3;
const SINGULAR_MARGIN_BASE: i32 = 32;
const SINGULAR_MARGIN_PER_DEPTH: i32 = 2;
""",
    "singular constants",
)

search = replace_once(
    search,
    """        ply: u16,
        path_len: usize,
        control: &C,
    ) -> Option<i32> {
""",
    """        ply: u16,
        path_len: usize,
        excluded_move: Option<ChessMove>,
        allow_singular: bool,
        exclusion_search: bool,
        control: &C,
    ) -> Option<i32> {
""",
    "negamax signature",
)

# Two root calls share one indentation level; the PVS verification call is nested one level deeper.
search = replace_exact_count(
    search,
    """                    1,
                    1,
                    control,
""",
    """                    1,
                    1,
                    None,
                    true,
                    false,
                    control,
""",
    2,
    "root direct negamax calls",
)
search = replace_once(
    search,
    """                        1,
                        1,
                        control,
                    ),
""",
    """                        1,
                        1,
                        None,
                        true,
                        false,
                        control,
                    ),
""",
    "root verification negamax call",
)

# The excluded root cannot consume the full-position TT record because it was computed with the
# excluded move available. Descendants receive excluded_move=None and may use valid TT entries.
search = replace_once(
    search,
    """        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = self.probe(key);
""",
    """        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = if excluded_move.is_some() {
            None
        } else {
            self.probe(key)
        };
""",
    "excluded-root TT isolation",
)

search = replace_once(
    search,
    """        let pruning_eligible = depth <= 3
            && null_window
""",
    """        let pruning_eligible = !exclusion_search
            && depth <= 3
            && null_window
""",
    "exclusion futility isolation",
)

singular_anchor = """        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        let moves = generate_legal_moves_mut(position);
"""
singular_block = """        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        // V15 singular-extension v1. A recent lower/exact TT move is only extended after a
        // reduced-depth exclusion search proves that every alternative fails below a threshold
        // close to the stored TT score. The feature is Gestalt-gated so the classical fallback is
        // exactly V14 production, and a one-ply cooldown prevents extension chains.
        let singular_move = if self.gestalt.is_some()
            && allow_singular
            && !exclusion_search
            && depth >= SINGULAR_MIN_DEPTH
            && !in_check
        {
            let candidate = table_entry.and_then(|entry| {
                let tt_move = entry.best_move?;
                let tt_score = score_from_tt(entry.score, ply);
                let depth_fresh = entry.depth.saturating_add(SINGULAR_TT_DEPTH_SLACK) >= depth;
                let useful_bound = matches!(entry.bound, Bound::Exact | Bound::Lower);
                let score_relevant = !null_window || tt_score >= beta;
                (depth_fresh
                    && useful_bound
                    && score_relevant
                    && tt_score.abs() < MATE_TT_THRESHOLD)
                    .then_some((tt_move, tt_score))
            });
            if let Some((tt_move, tt_score)) = candidate {
                let singular_margin =
                    SINGULAR_MARGIN_BASE + SINGULAR_MARGIN_PER_DEPTH * i32::from(depth);
                let singular_beta = tt_score.saturating_sub(singular_margin);
                let exclusion_depth = depth.saturating_sub(1) / 2;
                let exclusion = self.negamax(
                    position,
                    prior_history,
                    exclusion_depth,
                    singular_beta - 1,
                    singular_beta,
                    ply,
                    path_len,
                    Some(tt_move),
                    false,
                    true,
                    control,
                );
                let exclusion_score = exclusion?;
                (exclusion_score < singular_beta).then_some(tt_move)
            } else {
                None
            }
        } else {
            None
        };

        let moves = generate_legal_moves_mut(position);
"""
search = replace_once(search, singular_anchor, singular_block, "singular exclusion insertion")

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
            if excluded_move.is_none() {
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            }
            return Some(score);
        }
""",
    "excluded-root terminal TT isolation",
)

old_child = """            self.apply_leaf_move(position, prepared);
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                )
            } else {
                // Adaptive LMR v3. Only late ordinary quiets in non-check nodes are reduced. The
                // schedule becomes more aggressive only at deeper nodes and much later moves.
                // Any reduced alpha raise is re-probed at full depth before normal PVS verification,
                // so a reduced result can never directly become a principal score or beta cutoff.
                let reduction = if !in_check && quiet && !protected_killer && !gives_check {
                    history_adjusted_lmr_reduction(
                        depth,
                        move_index,
                        self.history.score(side, previous_context, context),
                    )
                } else {
                    0
                };
                let full_depth = depth - 1;
                let reduced_depth = full_depth.saturating_sub(reduction);
                let reduced_probe = self.negamax(
                    position,
                    prior_history,
                    reduced_depth,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                );
                let probe = match reduced_probe {
                    Some(reduced_child) if reduction > 0 && -reduced_child > alpha => self.negamax(
                        position,
                        prior_history,
                        full_depth,
                        -alpha - 1,
                        -alpha,
                        ply + 1,
                        path_len + 1,
                        control,
                    ),
                    reduced_probe => reduced_probe,
                };
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            full_depth,
                            -beta,
                            -alpha,
                            ply + 1,
                            path_len + 1,
                            control,
                        ),
                    probe => probe,
                }
            };
"""
new_child = """            self.apply_leaf_move(position, prepared);
            let singular_extension = u8::from(singular_move == Some(mv));
            let full_depth = depth
                .saturating_sub(1)
                .saturating_add(singular_extension);
            let child_allows_singular = !exclusion_search && singular_extension == 0;
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    full_depth,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    None,
                    child_allows_singular,
                    exclusion_search,
                    control,
                )
            } else {
                // Adaptive LMR v3 remains unchanged for ordinary moves. A move already proven
                // singular is never reduced, otherwise the extension would immediately be erased.
                let reduction = if singular_extension == 0
                    && !in_check
                    && quiet
                    && !protected_killer
                    && !gives_check
                {
                    history_adjusted_lmr_reduction(
                        depth,
                        move_index,
                        self.history.score(side, previous_context, context),
                    )
                } else {
                    0
                };
                let reduced_depth = full_depth.saturating_sub(reduction);
                let reduced_probe = self.negamax(
                    position,
                    prior_history,
                    reduced_depth,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    None,
                    child_allows_singular,
                    exclusion_search,
                    control,
                );
                let probe = match reduced_probe {
                    Some(reduced_child) if reduction > 0 && -reduced_child > alpha => self.negamax(
                        position,
                        prior_history,
                        full_depth,
                        -alpha - 1,
                        -alpha,
                        ply + 1,
                        path_len + 1,
                        None,
                        child_allows_singular,
                        exclusion_search,
                        control,
                    ),
                    reduced_probe => reduced_probe,
                };
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            full_depth,
                            -beta,
                            -alpha,
                            ply + 1,
                            path_len + 1,
                            None,
                            child_allows_singular,
                            exclusion_search,
                            control,
                        ),
                    probe => probe,
                }
            };
"""
search = replace_once(search, old_child, new_child, "recursive singular propagation")

search = replace_once(
    search,
    """        }) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
""",
    """        }) {
            if excluded_move == Some(mv) {
                continue;
            }
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
""",
    "excluded move skip",
)

search = replace_once(
    search,
    """            if quiet && null_window {
                let bonus = depth_bonus(depth);
""",
    """            if !exclusion_search && quiet && null_window {
                let bonus = depth_bonus(depth);
""",
    "exclusion history isolation",
)
search = replace_once(
    search,
    """            if alpha >= beta {
                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
""",
    """            if alpha >= beta {
                if !exclusion_search && !mv.kind().is_capture() && !mv.kind().is_promotion() {
""",
    "exclusion killer isolation",
)
search = replace_once(
    search,
    """        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
        Some(best)
""",
    """        if excluded_move.is_none() {
            self.table
                .store(key, depth, score_to_tt(best, ply), bound, best_move);
        }
        Some(best)
""",
    "excluded-root final TT isolation",
)

path.write_text(search)

root_path = Path("crates/chess-search/src/root_analysis.rs")
root = root_path.read_text()
root = replace_once(
    root,
    """                    1,
                    1,
                    &NeverStop,
""",
    """                    1,
                    1,
                    None,
                    true,
                    false,
                    &NeverStop,
""",
    "root analysis negamax call",
)
root_path.write_text(root)

print("applied V15 Gestalt-gated TT singular extension v1")
