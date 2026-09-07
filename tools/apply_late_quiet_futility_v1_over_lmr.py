#!/usr/bin/env python3
"""Apply conservative shallow late-quiet futility pruning over accepted LMR v3."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    "const MAX_SEARCH_PLY: usize = 256;",
    "const MAX_SEARCH_PLY: usize = 256;\nconst LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH: i32 = 180;\nconst LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;",
    "futility constants",
)

text = replace_once(
    text,
    '''        // Accepted conservative reverse futility pruning v1. Terminal positions have already been
        // handled; only shallow internal null-window nodes with non-pawn material are eligible.
        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        if depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position)
        {
            let static_eval = evaluate(position);
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }''',
    '''        // Accepted conservative reverse futility pruning v1. Terminal positions have already been
        // handled; only shallow internal null-window nodes with non-pawn material are eligible.
        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        let pruning_static_eval = if depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position)
        {
            Some(evaluate(position))
        } else {
            None
        };
        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }''',
    "share pruning static eval",
)

text = replace_once(
    text,
    '''            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            let child = if first_move {''',
    '''            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            if let Some(static_eval) = pruning_static_eval
                && should_prune_late_quiet_futility(
                    depth,
                    move_index,
                    in_check,
                    null_window,
                    quiet,
                    protected_killer,
                    gives_check,
                    static_eval,
                    alpha,
                    beta,
                )
            {
                position.unmake_move(mv, undo);
                move_index = move_index.saturating_add(1);
                continue;
            }
            let child = if first_move {''',
    "late quiet pruning",
)

text = replace_once(
    text,
    '''fn has_reverse_futility_material(position: &Position) -> bool {
    let us = position.side_to_move();''',
    '''#[allow(clippy::too_many_arguments)]
fn should_prune_late_quiet_futility(
    depth: u8,
    move_index: usize,
    in_check: bool,
    null_window: bool,
    quiet: bool,
    protected_killer: bool,
    gives_check: bool,
    static_eval: i32,
    alpha: i32,
    beta: i32,
) -> bool {
    depth <= 2
        && move_index >= LATE_QUIET_FUTILITY_MIN_MOVE_INDEX
        && !in_check
        && null_window
        && quiet
        && !protected_killer
        && !gives_check
        && alpha.abs() < MATE_TT_THRESHOLD
        && beta.abs() < MATE_TT_THRESHOLD
        && static_eval
            .saturating_add(LATE_QUIET_FUTILITY_MARGIN_PER_DEPTH * i32::from(depth))
            <= alpha
}

fn has_reverse_futility_material(position: &Position) -> bool {
    let us = position.side_to_move();''',
    "futility predicate",
)

text = replace_once(
    text,
    '''    #[test]
    fn mate_scores_are_normalized_across_transposition_ply() {''',
    '''    #[test]
    fn late_quiet_futility_only_prunes_safe_shallow_scout_candidates() {
        let prune = super::should_prune_late_quiet_futility(
            2, 4, false, true, true, false, false, -500, -100, -99,
        );
        assert!(prune);
        assert!(!super::should_prune_late_quiet_futility(
            2, 3, false, true, true, false, false, -500, -100, -99,
        ));
        assert!(!super::should_prune_late_quiet_futility(
            2, 4, false, true, true, false, true, -500, -100, -99,
        ));
        assert!(!super::should_prune_late_quiet_futility(
            2, 4, false, true, false, false, false, -500, -100, -99,
        ));
        assert!(!super::should_prune_late_quiet_futility(
            2, 4, false, false, true, false, false, -500, -100, 100,
        ));
        assert!(!super::should_prune_late_quiet_futility(
            3, 4, false, true, true, false, false, -800, -100, -99,
        ));
    }

    #[test]
    fn mate_scores_are_normalized_across_transposition_ply() {''',
    "futility predicate tests",
)

path.write_text(text)
