#!/usr/bin/env python3
"""Apply lightweight quiet-history gating to accepted LMR v3."""
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
    """const MAX_SEARCH_PLY: usize = 256;
const HISTORY_LMR_PROTECTION_THRESHOLD: u16 = 32;
const HISTORY_MAX: u16 = 512;""",
    "history constants",
)

text = replace_once(
    text,
    """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],""",
    """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    quiet_history: [[u16; 64]; 64],""",
    "history field",
)

text = replace_once(
    text,
    """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],""",
    """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            quiet_history: [[0; 64]; 64],""",
    "history init",
)

text = replace_once(
    text,
    """        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];""",
    """        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.quiet_history = [[0; 64]; 64];""",
    "fixed-depth history reset",
)

text = replace_once(
    text,
    """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        let mut last_completed = None;""",
    """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.quiet_history = [[0; 64]; 64];
        let mut last_completed = None;""",
    "iterative history reset",
)

text = replace_once(
    text,
    """        while let Some(mv) = picker.next(position) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let undo = position.make_move(mv);""",
    """        while let Some(mv) = picker.next(position) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let history_score = if quiet {
                self.quiet_history[usize::from(mv.from().index())][usize::from(mv.to().index())]
            } else {
                0
            };
            let undo = position.make_move(mv);""",
    "history read",
)

text = replace_once(
    text,
    """                let reduction = if !in_check && quiet && !protected_killer && !gives_check {
                    lmr_v3_reduction(depth, move_index)
                } else {
                    0
                };""",
    """                let reduction = if !in_check && quiet && !protected_killer && !gives_check {
                    history_gated_lmr_reduction(lmr_v3_reduction(depth, move_index), history_score)
                } else {
                    0
                };""",
    "history-gated reduction",
)

text = replace_once(
    text,
    """                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
                    let killers = &mut self.killers[usize::from(ply)];
                    if killers[0] != Some(mv) {
                        killers[1] = killers[0];
                        killers[0] = Some(mv);
                    }
                }
                break;""",
    """                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
                    self.record_quiet_history_cutoff(mv, depth);
                    let killers = &mut self.killers[usize::from(ply)];
                    if killers[0] != Some(mv) {
                        killers[1] = killers[0];
                        killers[0] = Some(mv);
                    }
                }
                break;""",
    "history cutoff update",
)

text = replace_once(
    text,
    """    fn fallback_result(&self, position: &mut Position, prior_history: &[u64]) -> SearchResult {""",
    """    fn record_quiet_history_cutoff(&mut self, mv: ChessMove, depth: u8) {
        let from = usize::from(mv.from().index());
        let to = usize::from(mv.to().index());
        let depth = u16::from(depth);
        let bonus = depth.saturating_mul(depth).min(64);
        self.quiet_history[from][to] = self.quiet_history[from][to]
            .saturating_add(bonus)
            .min(HISTORY_MAX);
    }

    fn fallback_result(&self, position: &mut Position, prior_history: &[u64]) -> SearchResult {""",
    "history update method",
)

text = replace_once(
    text,
    """fn has_reverse_futility_material(position: &Position) -> bool {""",
    """fn history_gated_lmr_reduction(base_reduction: u8, history_score: u16) -> u8 {
    if history_score >= HISTORY_LMR_PROTECTION_THRESHOLD {
        base_reduction.saturating_sub(1)
    } else {
        base_reduction
    }
}

fn has_reverse_futility_material(position: &Position) -> bool {""",
    "history helper",
)

text = replace_once(
    text,
    """        MATE_SCORE, SearchControl, Searcher, has_two_prior_occurrences, iterative_deepening,
        score_from_tt, score_to_tt, search, search_mut, tt_entries_for_megabytes,""",
    """        MATE_SCORE, SearchControl, Searcher, has_two_prior_occurrences,
        history_gated_lmr_reduction, iterative_deepening, score_from_tt, score_to_tt, search,
        search_mut, tt_entries_for_megabytes,""",
    "history test import",
)

text = replace_once(
    text,
    """    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {""",
    """    #[test]
    fn quiet_history_only_softens_an_existing_lmr_reduction() {
        assert_eq!(history_gated_lmr_reduction(0, 512), 0);
        assert_eq!(history_gated_lmr_reduction(2, 31), 2);
        assert_eq!(history_gated_lmr_reduction(2, 32), 1);
        assert_eq!(history_gated_lmr_reduction(3, 512), 2);
    }

    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {""",
    "history helper test",
)

path.write_text(text)
