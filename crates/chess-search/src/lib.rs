//! Classical reference search.
//!
//! The reference path stays intentionally inspectable: iterative deepening drives a reversible
//! negamax/alpha-beta search with deterministic move ordering and a bounded direct-mapped
//! transposition table. It is the control group for later tactical and strategic search research.

mod move_picker;
mod quiescence;

use chess_core::{ChessMove, Position, generate_legal_moves_mut};
use chess_eval::evaluate;
use move_picker::MovePicker;

/// Scores at or above this range encode forced mate rather than static evaluation.
pub const MATE_SCORE: i32 = 30_000;
/// Default number of entries in the bounded reference transposition table.
pub const DEFAULT_TT_ENTRIES: usize = 1 << 15;
const BYTES_PER_MEGABYTE: usize = 1024 * 1024;

const INFINITY: i32 = 32_000;
const MATE_TT_THRESHOLD: i32 = MATE_SCORE - 1_000;
const MAX_SEARCH_PLY: usize = 256;

/// Result of one deterministic reference search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchResult {
    pub best_move: Option<ChessMove>,
    pub score: i32,
    pub depth: u8,
    pub nodes: u64,
    pub tt_hits: u64,
}

/// Result of an interruptible iterative search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchOutcome {
    /// Last fully completed iteration, or a legal depth-zero fallback if interruption happened
    /// before depth one completed. Node/hit counters include partial work from the aborted depth.
    pub result: SearchResult,
    /// True when the control requested termination before `max_depth` completed.
    pub stopped: bool,
}

/// Cheap caller-provided cancellation/budget check.
///
/// The trait is generic through recursive search, so the ordinary `NeverStop` path can be
/// monomorphised without a dynamic-dispatch call in the hot loop.
pub trait SearchControl {
    #[must_use]
    fn should_stop(&self, nodes: u64) -> bool;

    /// Decide whether another iterative-deepening pass should begin after a completed root result.
    /// The default keeps depth/node-only and deterministic reference searches unchanged.
    #[must_use]
    fn should_start_next_iteration(&self, _completed: SearchResult) -> bool {
        true
    }
}

#[derive(Clone, Copy, Default)]
struct NeverStop;

impl SearchControl for NeverStop {
    fn should_stop(&self, _nodes: u64) -> bool {
        false
    }
}

/// Reusable search state.
///
/// Long-lived engine frontends should keep one `Searcher` so the table allocation is not repeated
/// for every command. The convenience free functions below create a temporary searcher.
pub struct Searcher {
    table: TranspositionTable,
    nodes: u64,
    tt_hits: u64,
    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
}

impl Searcher {
    #[must_use]
    pub fn with_tt_entries(entries: usize) -> Self {
        Self {
            table: TranspositionTable::new(entries),
            nodes: 0,
            tt_hits: 0,
            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
        }
    }

    /// Construct search state with a transposition table bounded by whole mebibytes.
    ///
    /// This is the production-facing sizing API. The deterministic reference default remains
    /// entry-count based so benchmark identity does not depend on platform allocator details.
    #[must_use]
    pub fn with_tt_megabytes(megabytes: usize) -> Self {
        Self::with_tt_entries(tt_entries_for_megabytes(megabytes))
    }

    #[must_use]
    pub fn tt_capacity_entries(&self) -> usize {
        self.table.len()
    }

    /// Search one exact nominal depth while restoring `position` exactly.
    #[must_use]
    pub fn search_depth(&mut self, position: &mut Position, depth: u8) -> SearchResult {
        self.search_depth_with_history(position, &[], depth)
    }

    /// Search one exact depth with repetition keys for positions preceding the supplied root.
    #[must_use]
    pub fn search_depth_with_history(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
    ) -> SearchResult {
        #[cfg(debug_assertions)]
        let root = position.clone();

        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        let result = self
            .search_root(position, prior_history, depth, &NeverStop)
            .expect("NeverStop cannot interrupt search");

        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);
        result
    }

    /// Search depths `1..=max_depth`, retaining the transposition table between iterations.
    #[must_use]
    pub fn iterative_deepening(&mut self, position: &mut Position, max_depth: u8) -> SearchResult {
        self.iterative_deepening_with_history(position, &[], max_depth)
    }

    /// Iteratively search with repetition keys for positions preceding the supplied root.
    #[must_use]
    pub fn iterative_deepening_with_history(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        max_depth: u8,
    ) -> SearchResult {
        self.iterative_deepening_controlled_with_history(
            position,
            prior_history,
            max_depth,
            &NeverStop,
        )
        .result
    }

    /// Iteratively search while consulting `control` at recursive node boundaries.
    #[must_use]
    pub fn iterative_deepening_controlled<C: SearchControl>(
        &mut self,
        position: &mut Position,
        max_depth: u8,
        control: &C,
    ) -> SearchOutcome {
        self.iterative_deepening_controlled_with_history(position, &[], max_depth, control)
    }

    /// Iteratively search under cooperative control and complete game-history context.
    ///
    /// `prior_history` contains repetition keys for positions before the current root; the current
    /// root itself must not be included. Search-path keys live in a fixed array owned by `Searcher`,
    /// so recursive repetition checks add no heap allocation to the hot path.
    #[must_use]
    pub fn iterative_deepening_controlled_with_history<C: SearchControl>(
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
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        let mut last_completed = None;

        for depth in 1..=max_depth {
            self.nodes = self.nodes.saturating_add(1);
            match self.search_root(position, prior_history, depth, control) {
                Some(mut result) => {
                    result.nodes = self.nodes;
                    result.tt_hits = self.tt_hits;
                    last_completed = Some(result);
                    if depth < max_depth && !control.should_start_next_iteration(result) {
                        #[cfg(debug_assertions)]
                        debug_assert_eq!(*position, root);
                        return SearchOutcome {
                            result,
                            stopped: true,
                        };
                    }
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

        let result = last_completed.expect("positive max_depth completes at least depth one");
        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);
        SearchOutcome {
            result,
            stopped: false,
        }
    }

    fn search_root<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        control: &C,
    ) -> Option<SearchResult> {
        // Control must precede even an exact root TT hit; otherwise a cached result can make an
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
        let table_entry = self.probe(key);
        if let Some(entry) = table_entry
            && entry.depth >= depth
            && entry.bound == Bound::Exact
        {
            return Some(SearchResult {
                best_move: entry.best_move,
                score: score_from_tt(entry.score, 0),
                depth,
                nodes: self.nodes,
                tt_hits: self.tt_hits,
            });
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
        let mut alpha = -INFINITY;
        self.path_keys[0] = repetition_key;

        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -INFINITY,
                    -alpha,
                    1,
                    1,
                    control,
                )
            } else {
                // Later root moves first get a null-window probe. Good ordering
                // should make most fail low; only alpha-raising moves are re-searched.
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
                    Some(probe_child) if -probe_child > alpha => self.negamax(
                        position,
                        prior_history,
                        depth - 1,
                        -INFINITY,
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
        }

        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            Bound::Exact,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))
    }

    #[allow(clippy::too_many_arguments)]
    fn negamax<C: SearchControl>(
        &mut self,
        position: &mut Position,
        prior_history: &[u64],
        depth: u8,
        mut alpha: i32,
        beta: i32,
        ply: u16,
        path_len: usize,
        control: &C,
    ) -> Option<i32> {
        self.nodes = self.nodes.saturating_add(1);
        if control.should_stop(self.nodes) {
            return None;
        }

        if depth == 0 {
            return self.quiescence(position, prior_history, alpha, beta, ply, path_len, control);
        }

        let repetition_key = position.repetition_key().raw();
        if is_rule_draw(
            position,
            repetition_key,
            prior_history,
            &self.path_keys[..path_len],
        ) {
            // Checkmate ends the game before a draw claim can be made. We only need legal move
            // generation in the draw path when the side to move is actually in check; otherwise a
            // claimable draw can return immediately.
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
        let table_entry = self.probe(key);

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
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best = -INFINITY;
        let mut best_move = None;

        let mut moves = moves;
        let killers = self.killers[usize::from(ply)];
        let mut picker = MovePicker::new(&mut moves, hint, killers);
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
                    ply + 1,
                    path_len + 1,
                    control,
                )
            } else {
                // Principal variation search probes later moves with a one-point
                // window and verifies only genuine alpha improvements.
                let probe = self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
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
                            ply + 1,
                            path_len + 1,
                            control,
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
                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
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
        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
        Some(best)
    }

    fn fallback_result(&self, position: &mut Position, prior_history: &[u64]) -> SearchResult {
        let repetition_key = position.repetition_key().raw();
        let moves = generate_legal_moves_mut(position);
        let (best_move, score) = if moves.is_empty() {
            (None, terminal_score(position, 0))
        } else if is_rule_draw(position, repetition_key, prior_history, &[]) {
            (Some(moves[0]), 0)
        } else {
            (Some(moves[0]), evaluate(position))
        };
        SearchResult {
            best_move,
            score,
            depth: 0,
            nodes: self.nodes,
            tt_hits: self.tt_hits,
        }
    }

    fn probe(&mut self, key: u64) -> Option<TtEntry> {
        let entry = self.table.probe(key);
        if entry.is_some() {
            self.tt_hits = self.tt_hits.saturating_add(1);
        }
        entry
    }

    fn result(&self, best_move: Option<ChessMove>, score: i32, depth: u8) -> SearchResult {
        SearchResult {
            best_move,
            score,
            depth,
            nodes: self.nodes,
            tt_hits: self.tt_hits,
        }
    }
}

/// Convert a whole-mebibyte TT budget into the maximum number of complete entries that fit.
#[must_use]
pub fn tt_entries_for_megabytes(megabytes: usize) -> usize {
    let bytes = megabytes.saturating_mul(BYTES_PER_MEGABYTE);
    (bytes / core::mem::size_of::<TtEntry>()).max(1)
}

impl Default for Searcher {
    fn default() -> Self {
        Self::with_tt_entries(DEFAULT_TT_ENTRIES)
    }
}

/// Search a position to one exact nominal depth.
#[must_use]
pub fn search(position: &Position, depth: u8) -> SearchResult {
    let mut working = position.clone();
    search_mut(&mut working, depth)
}

/// Search a mutable working position to one exact depth, restoring it before returning.
#[must_use]
pub fn search_mut(position: &mut Position, depth: u8) -> SearchResult {
    Searcher::default().search_depth(position, depth)
}

/// Iteratively search depths `1..=max_depth` using one table across all iterations.
#[must_use]
pub fn iterative_deepening(position: &Position, max_depth: u8) -> SearchResult {
    let mut working = position.clone();
    Searcher::default().iterative_deepening(&mut working, max_depth)
}

fn is_rule_draw(
    position: &Position,
    repetition_key: u64,
    prior_history: &[u64],
    search_path: &[u64],
) -> bool {
    position.halfmove_clock() >= 100
        || position.is_insufficient_material()
        || has_two_prior_occurrences(repetition_key, prior_history, search_path)
}

fn has_two_prior_occurrences(key: u64, prior_history: &[u64], search_path: &[u64]) -> bool {
    let mut matches = 0_u8;
    for &candidate in prior_history.iter().chain(search_path) {
        if candidate == key {
            matches += 1;
            if matches >= 2 {
                return true;
            }
        }
    }
    false
}

fn terminal_score(position: &Position, ply: u16) -> i32 {
    if position.is_in_check(position.side_to_move()) {
        -MATE_SCORE + i32::from(ply)
    } else {
        0
    }
}

fn score_to_tt(score: i32, ply: u16) -> i32 {
    let ply = i32::from(ply);
    if score >= MATE_TT_THRESHOLD {
        score + ply
    } else if score <= -MATE_TT_THRESHOLD {
        score - ply
    } else {
        score
    }
}

fn score_from_tt(score: i32, ply: u16) -> i32 {
    let ply = i32::from(ply);
    if score >= MATE_TT_THRESHOLD {
        score - ply
    } else if score <= -MATE_TT_THRESHOLD {
        score + ply
    } else {
        score
    }
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
#[repr(u8)]
enum Bound {
    Exact,
    Lower,
    Upper,
}

#[derive(Clone, Copy, Debug)]
struct TtEntry {
    valid: bool,
    key: u64,
    depth: u8,
    score: i32,
    bound: Bound,
    best_move: Option<ChessMove>,
}

impl TtEntry {
    const EMPTY: Self = Self {
        valid: false,
        key: 0,
        depth: 0,
        score: 0,
        bound: Bound::Exact,
        best_move: None,
    };
}

struct TranspositionTable {
    entries: Vec<TtEntry>,
}

impl TranspositionTable {
    fn new(entries: usize) -> Self {
        Self {
            entries: vec![TtEntry::EMPTY; entries],
        }
    }

    fn len(&self) -> usize {
        self.entries.len()
    }

    fn probe(&self, key: u64) -> Option<TtEntry> {
        let slot = self.slot(key)?;
        let entry = self.entries[slot];
        (entry.valid && entry.key == key).then_some(entry)
    }

    fn store(
        &mut self,
        key: u64,
        depth: u8,
        score: i32,
        bound: Bound,
        best_move: Option<ChessMove>,
    ) {
        let Some(slot) = self.slot(key) else {
            return;
        };
        let old = self.entries[slot];
        if !old.valid || old.key != key || depth >= old.depth {
            self.entries[slot] = TtEntry {
                valid: true,
                key,
                depth,
                score,
                bound,
                best_move,
            };
        }
    }

    fn slot(&self, key: u64) -> Option<usize> {
        (!self.entries.is_empty()).then(|| key as usize % self.entries.len())
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position};

    use super::{
        MATE_SCORE, SearchControl, Searcher, has_two_prior_occurrences, iterative_deepening,
        score_from_tt, score_to_tt, search, search_mut, tt_entries_for_megabytes,
    };

    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
        let expected = (1024 * 1024) / core::mem::size_of::<super::TtEntry>();
        assert_eq!(tt_entries_for_megabytes(1), expected);
        assert_eq!(
            Searcher::with_tt_megabytes(1).tt_capacity_entries(),
            expected
        );
        assert_eq!(tt_entries_for_megabytes(0), 1);
    }

    struct NodeStop(u64);

    impl SearchControl for NodeStop {
        fn should_stop(&self, nodes: u64) -> bool {
            nodes >= self.0
        }
    }

    #[test]
    fn search_returns_a_legal_starting_move_without_mutating_root() {
        let root = Position::startpos();
        let legal = root.legal_moves();
        let result = search(&root, 2);
        assert!(
            result
                .best_move
                .is_some_and(|mv| legal.as_slice().contains(&mv))
        );
        assert!(result.nodes > 1);
        assert_eq!(root, Position::startpos());
    }

    #[test]
    fn mutable_search_restores_the_position_exactly() {
        let mut position = Position::from_fen(
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        )
        .expect("valid FEN");
        let root = position.clone();
        let _ = search_mut(&mut position, 2);
        assert_eq!(position, root);
    }

    #[test]
    fn finds_a_mate_in_one() {
        let root = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1").expect("valid FEN");
        let result = search(&root, 1);
        assert!(result.score >= MATE_SCORE - 1);

        let mut child = root.clone();
        let mv = result.best_move.expect("mate has a best move");
        let _undo = child.make_move(mv);
        assert!(child.legal_moves().is_empty());
        assert!(child.is_in_check(Color::Black));
    }

    #[test]
    fn stalemate_is_zero() {
        let root = Position::from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1").expect("valid FEN");
        let result = search(&root, 3);
        assert_eq!(result.best_move, None);
        assert_eq!(result.score, 0);
    }

    #[test]
    fn iterative_deepening_reuses_table_and_matches_exact_score() {
        let root = Position::startpos();
        let direct = search(&root, 3);
        let iterative = iterative_deepening(&root, 3);
        assert_eq!(iterative.depth, 3);
        assert_eq!(iterative.score, direct.score);
        assert!(iterative.tt_hits > 0);
        assert_eq!(root, Position::startpos());
    }

    #[test]
    fn controlled_search_stops_and_restores_position() {
        let mut root = Position::startpos();
        let original = root.clone();
        let mut searcher = Searcher::default();
        let outcome = searcher.iterative_deepening_controlled(&mut root, 8, &NodeStop(25));
        assert!(outcome.stopped);
        assert!(outcome.result.nodes >= 25);
        assert!(outcome.result.best_move.is_some());
        assert_eq!(root, original);
    }

    #[test]
    fn cached_root_result_cannot_bypass_stop_control() {
        let mut root = Position::startpos();
        let original = root.clone();
        let mut searcher = Searcher::default();
        let _warm = searcher.search_depth(&mut root, 2);
        let outcome = searcher.iterative_deepening_controlled(&mut root, 2, &NodeStop(1));
        assert!(outcome.stopped);
        assert_eq!(outcome.result.depth, 0);
        assert_eq!(root, original);
    }

    #[test]
    fn threefold_history_is_draw_even_with_non_draw_tt_entry() {
        let mut root = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 0 1").expect("valid FEN");
        let original = root.clone();
        let mut searcher = Searcher::default();
        let warm = searcher.search_depth(&mut root, 1);
        assert!(warm.score > 0);

        let key = root.repetition_key().raw();
        let drawn = searcher.search_depth_with_history(&mut root, &[key, key], 1);
        assert_eq!(drawn.score, 0);
        assert!(drawn.best_move.is_some());
        assert_eq!(root, original);
    }

    #[test]
    fn fifty_move_rule_is_draw_but_checkmate_takes_precedence() {
        let queen_up = Position::from_fen("7k/8/8/8/8/8/6Q1/K7 w - - 100 1").expect("valid FEN");
        assert_eq!(search(&queen_up, 2).score, 0);

        let checkmate = Position::from_fen("7k/6Q1/5K2/8/8/8/8/8 b - - 100 1").expect("valid FEN");
        let result = search(&checkmate, 2);
        assert_eq!(result.best_move, None);
        assert_eq!(result.score, -MATE_SCORE);
    }

    #[test]
    fn insufficient_material_is_drawn_before_static_evaluation() {
        let root = Position::from_fen("7k/8/8/8/8/8/6B1/K7 w - - 0 1").expect("valid FEN");
        let result = search(&root, 3);
        assert_eq!(result.score, 0);
        assert!(result.best_move.is_some());
    }

    #[test]
    fn repetition_counter_combines_game_and_search_history() {
        let key = 17_u64;
        assert!(!has_two_prior_occurrences(key, &[key], &[]));
        assert!(has_two_prior_occurrences(key, &[key], &[key]));
        assert!(has_two_prior_occurrences(key, &[], &[key, key]));
    }

    #[test]
    fn zero_sized_table_remains_correct() {
        let mut root = Position::from_fen("7k/5Q2/6K1/8/8/8/8/8 w - - 0 1").expect("valid FEN");
        let mut searcher = Searcher::with_tt_entries(0);
        let result = searcher.search_depth(&mut root, 1);
        assert!(result.score >= MATE_SCORE - 1);
        assert_eq!(result.tt_hits, 0);
    }

    #[test]
    fn mate_scores_are_normalized_across_transposition_ply() {
        let winning = MATE_SCORE - 7;
        let stored = score_to_tt(winning, 7);
        assert_eq!(score_from_tt(stored, 3), MATE_SCORE - 3);

        let losing = -MATE_SCORE + 7;
        let stored = score_to_tt(losing, 7);
        assert_eq!(score_from_tt(stored, 3), -MATE_SCORE + 3);
    }
}
