#!/usr/bin/env python3
"""Apply conservative tactical ProbCut over accepted LQF production."""
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
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;",
    """const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;
const PROBCUT_MIN_DEPTH: u8 = 5;
const PROBCUT_REDUCTION: u8 = 3;
const PROBCUT_MARGIN: i32 = 180;
const PROBCUT_STATIC_MARGIN: i32 = 120;""",
    "probcut constants",
)

text = replace_once(
    text,
    '''        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best = -INFINITY;''',
    '''        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        // Conservative tactical ProbCut v1. This is restricted to deep scout nodes whose static
        // evaluation is already near beta. Only tactical moves are probed, at reduced depth and
        // against a widened beta margin. A speculative fail-high returns the widened bound without
        // storing a bound for the current node or recording a killer.
        if probcut_v1_eligible(depth, in_check, null_window, beta)
            && has_reverse_futility_material(position)
        {
            let static_eval = evaluate(position);
            if static_eval >= beta.saturating_sub(PROBCUT_STATIC_MARGIN) {
                let prob_beta = beta.saturating_add(PROBCUT_MARGIN);
                let reduced_depth = depth
                    .saturating_sub(1)
                    .saturating_sub(PROBCUT_REDUCTION);
                let mut probcut_moves = moves.clone();
                let mut probcut_picker = MovePicker::new(&mut probcut_moves, None, [None; 2]);
                while let Some(mv) = probcut_picker.next(position) {
                    if !mv.kind().is_capture() && !mv.kind().is_promotion() {
                        break;
                    }
                    let undo = position.make_move(mv);
                    self.nodes = self.nodes.saturating_add(1);
                    let child = self.negamax(
                        position,
                        prior_history,
                        reduced_depth,
                        -prob_beta,
                        -prob_beta + 1,
                        ply + 1,
                        path_len + 1,
                        control,
                    );
                    position.unmake_move(mv, undo);
                    let score = -child?;
                    if score >= prob_beta {
                        return Some(prob_beta);
                    }
                }
            }
        }

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best = -INFINITY;''',
    "probcut search",
)

text = replace_once(
    text,
    '''#[allow(clippy::too_many_arguments)]
fn should_prune_late_quiet_futility(''',
    '''fn probcut_v1_eligible(depth: u8, in_check: bool, null_window: bool, beta: i32) -> bool {
    depth >= PROBCUT_MIN_DEPTH
        && !in_check
        && null_window
        && beta.abs() < MATE_TT_THRESHOLD.saturating_sub(PROBCUT_MARGIN)
}

#[allow(clippy::too_many_arguments)]
fn should_prune_late_quiet_futility(''',
    "probcut predicate",
)

text = replace_once(
    text,
    '''    #[test]
    fn late_quiet_futility_only_prunes_safe_shallow_scout_candidates() {''',
    '''    #[test]
    fn probcut_v1_gate_is_deep_scout_only_and_avoids_mate_band() {
        assert!(super::probcut_v1_eligible(5, false, true, 100));
        assert!(!super::probcut_v1_eligible(4, false, true, 100));
        assert!(!super::probcut_v1_eligible(5, true, true, 100));
        assert!(!super::probcut_v1_eligible(5, false, false, 100));
        assert!(!super::probcut_v1_eligible(
            5,
            false,
            true,
            super::MATE_TT_THRESHOLD - super::PROBCUT_MARGIN,
        ));
    }

    #[test]
    fn late_quiet_futility_only_prunes_safe_shallow_scout_candidates() {''',
    "probcut tests",
)

path.write_text(text)
