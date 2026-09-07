#!/usr/bin/env python3
"""Apply one-budget single-evasion check extension over accepted production search."""
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
    "const LATE_QUIET_FUTILITY_MIN_MOVE_INDEX: usize = 4;\nconst FORCED_EVASION_EXTENSION_BUDGET: u8 = 1;",
    "extension budget constant",
)

text = replace_once(
    text,
    '''        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;''',
    '''        let root_in_check = position.is_in_check(position.side_to_move());
        let (root_child_depth, root_extension_budget) = forced_evasion_child_depth(
            depth,
            root_in_check,
            moves.len(),
            FORCED_EVASION_EXTENSION_BUDGET,
        );

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;''',
    "root extension setup",
)

for label, old, new in [
    (
        "root first move",
        '''                    prior_history,
                    depth - 1,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    control,''',
        '''                    prior_history,
                    root_child_depth,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    root_extension_budget,
                    control,''',
    ),
    (
        "root scout move",
        '''                    prior_history,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    1,
                    1,
                    control,''',
        '''                    prior_history,
                    root_child_depth,
                    -alpha - 1,
                    -alpha,
                    1,
                    1,
                    root_extension_budget,
                    control,''',
    ),
    (
        "root verification move",
        '''                        prior_history,
                        depth - 1,
                        -INFINITY,
                        -alpha,
                        1,
                        1,
                        control,''',
        '''                        prior_history,
                        root_child_depth,
                        -INFINITY,
                        -alpha,
                        1,
                        1,
                        root_extension_budget,
                        control,''',
    ),
]:
    text = replace_once(text, old, new, label)

text = replace_once(
    text,
    '''        beta: i32,
        ply: u16,
        path_len: usize,
        control: &C,''',
    '''        beta: i32,
        ply: u16,
        path_len: usize,
        extension_budget: u8,
        control: &C,''',
    "negamax extension parameter",
)

text = replace_once(
    text,
    '''        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        let hint = table_entry.and_then(|entry| entry.best_move);''',
    '''        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        let (full_depth, child_extension_budget) =
            forced_evasion_child_depth(depth, in_check, moves.len(), extension_budget);

        let hint = table_entry.and_then(|entry| entry.best_move);''',
    "recursive extension setup",
)

text = replace_once(
    text,
    '''                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,''',
    '''                    prior_history,
                    full_depth,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    child_extension_budget,
                    control,''',
    "recursive first move",
)

text = replace_once(
    text,
    '''                let full_depth = depth - 1;
                let reduced_depth = full_depth.saturating_sub(reduction);''',
    '''                let reduced_depth = full_depth.saturating_sub(reduction);''',
    "reuse extension-aware full depth",
)

# Four recursive negamax calls in the later-move PVS/LMR path all inherit the child's remaining
# extension budget. Insert the argument immediately after path_len + 1.
needle = '''                    ply + 1,
                    path_len + 1,
                    control,'''
replacement = '''                    ply + 1,
                    path_len + 1,
                    child_extension_budget,
                    control,'''
count = text.count(needle)
if count != 2:
    raise SystemExit(f"later recursive calls: expected 2 matches, found {count}")
text = text.replace(needle, replacement)

needle = '''                            ply + 1,
                            path_len + 1,
                            control,'''
replacement = '''                            ply + 1,
                            path_len + 1,
                            child_extension_budget,
                            control,'''
count = text.count(needle)
if count != 1:
    raise SystemExit(f"PVS verification call: expected 1 match, found {count}")
text = text.replace(needle, replacement)

# Add the tiny pure policy helper near LMR helpers so its behavior is unit-testable without relying
# on a fragile tactical FEN.
marker = '''fn lmr_v3_reduction(depth: u8, move_index: usize) -> u8 {'''
helper = '''fn forced_evasion_child_depth(
    depth: u8,
    in_check: bool,
    legal_moves: usize,
    extension_budget: u8,
) -> (u8, u8) {
    debug_assert!(depth > 0);
    let extend = in_check && legal_moves == 1 && extension_budget > 0;
    if extend {
        (depth, extension_budget - 1)
    } else {
        (depth - 1, extension_budget)
    }
}

fn lmr_v3_reduction(depth: u8, move_index: usize) -> u8 {'''
text = replace_once(text, marker, helper, "forced evasion helper")

# Add focused policy regression.
marker = '''    #[test]
    fn late_quiet_futility_only_prunes_safe_shallow_scout_candidates() {'''
regression = '''    #[test]
    fn forced_evasion_extension_is_single_budget_and_only_for_one_legal_reply() {
        assert_eq!(forced_evasion_child_depth(4, true, 1, 1), (4, 0));
        assert_eq!(forced_evasion_child_depth(4, true, 1, 0), (3, 0));
        assert_eq!(forced_evasion_child_depth(4, true, 2, 1), (3, 1));
        assert_eq!(forced_evasion_child_depth(4, false, 1, 1), (3, 1));
    }

    #[test]
    fn late_quiet_futility_only_prunes_safe_shallow_scout_candidates() {'''
text = replace_once(text, marker, regression, "forced evasion regression")

path.write_text(text)

# Off-hot-path root analysis calls the same negamax and gets the same one-extension-per-line budget.
path = Path("crates/chess-search/src/root_analysis.rs")
text = path.read_text()
text = replace_once(
    text,
    '''use super::{INFINITY, MAX_SEARCH_PLY, NeverStop, Searcher, is_rule_draw};''',
    '''use super::{
    FORCED_EVASION_EXTENSION_BUDGET, INFINITY, MAX_SEARCH_PLY, NeverStop, Searcher, is_rule_draw,
};''',
    "root analysis extension import",
)
text = replace_once(
    text,
    '''                    1,
                    1,
                    &NeverStop,''',
    '''                    1,
                    1,
                    FORCED_EVASION_EXTENSION_BUDGET,
                    &NeverStop,''',
    "root analysis negamax budget",
)
path.write_text(text)
