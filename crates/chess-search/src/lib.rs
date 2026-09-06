//! Classical reference search.
//!
//! The reference path stays intentionally inspectable: iterative deepening drives a reversible
//! negamax/alpha-beta search with deterministic move ordering and a bounded direct-mapped
//! transposition table. It is the control group for later tactical and strategic search research.

use chess_core::{ChessMove, MoveList, Position, generate_legal_moves_mut};
use chess_eval::evaluate;

/// Scores at or above this range encode forced mate rather than static evaluation.
pub const MATE_SCORE: i32 = 30_000;
/// Default number of entries in the bounded reference transposition table.
pub const DEFAULT_TT_ENTRIES: usize = 1 << 15;

const INFINITY: i32 = 32_000;
const MATE_TT_THRESHOLD: i32 = MATE_SCORE - 1_000;

/// Result of one deterministic reference search.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SearchResult {
    pub best_move: Option<ChessMove>,
    pub score: i32,
    pub depth: u8,
    pub nodes: u64,
    pub tt_hits: u64,
}

/// Reusable search state.
///
/// Long-lived engine frontends should keep one `Searcher` so the table allocation is not repeated
/// for every command. The convenience free functions below create a temporary searcher.
pub struct Searcher {
    table: TranspositionTable,
    nodes: u64,
    tt_hits: u64,
}

impl Searcher {
    #[must_use]
    pub fn with_tt_entries(entries: usize) -> Self {
        Self {
            table: TranspositionTable::new(entries),
            nodes: 0,
            tt_hits: 0,
        }
    }

    /// Search one exact nominal depth while restoring `position` exactly.
    #[must_use]
    pub fn search_depth(&mut self, position: &mut Position, depth: u8) -> SearchResult {
        #[cfg(debug_assertions)]
        let root = position.clone();

        self.nodes = 1;
        self.tt_hits = 0;
        let result = self.search_root(position, depth);

        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);
        result
    }

    /// Search depths `1..=max_depth`, retaining the transposition table between iterations.
    ///
    /// Reported nodes and table hits are cumulative across all completed iterations because those
    /// counters describe the actual work performed by iterative deepening.
    #[must_use]
    pub fn iterative_deepening(&mut self, position: &mut Position, max_depth: u8) -> SearchResult {
        if max_depth == 0 {
            return self.search_depth(position, 0);
        }

        #[cfg(debug_assertions)]
        let root = position.clone();

        let mut total_nodes = 0_u64;
        let mut total_hits = 0_u64;
        let mut result = self.search_depth(position, 1);
        total_nodes = total_nodes.saturating_add(result.nodes);
        total_hits = total_hits.saturating_add(result.tt_hits);

        for depth in 2..=max_depth {
            result = self.search_depth(position, depth);
            total_nodes = total_nodes.saturating_add(result.nodes);
            total_hits = total_hits.saturating_add(result.tt_hits);
        }

        result.nodes = total_nodes;
        result.tt_hits = total_hits;

        #[cfg(debug_assertions)]
        debug_assert_eq!(*position, root);
        result
    }

    fn search_root(&mut self, position: &mut Position, depth: u8) -> SearchResult {
        let key = position.zobrist_key().raw();
        let table_entry = self.probe(key);
        if let Some(entry) = table_entry {
            if entry.depth >= depth && entry.bound == Bound::Exact {
                return SearchResult {
                    best_move: entry.best_move,
                    score: score_from_tt(entry.score, 0),
                    depth,
                    nodes: self.nodes,
                    tt_hits: self.tt_hits,
                };
            }
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, 0);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return self.result(None, score, depth);
        }

        if depth == 0 {
            let score = evaluate(position);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return self.result(None, score, depth);
        }

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best_move = None;
        let mut best_score = -INFINITY;
        let mut alpha = -INFINITY;

        for mv in OrderedMoves::new(&moves, hint) {
            let undo = position.make_move(mv);
            let score = -self.negamax(position, depth - 1, -INFINITY, -alpha, 1);
            position.unmake_move(mv, undo);

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
        self.result(best_move, best_score, depth)
    }

    fn negamax(
        &mut self,
        position: &mut Position,
        depth: u8,
        mut alpha: i32,
        beta: i32,
        ply: u16,
    ) -> i32 {
        self.nodes = self.nodes.saturating_add(1);
        let key = position.zobrist_key().raw();
        let alpha_original = alpha;
        let table_entry = self.probe(key);

        if let Some(entry) = table_entry {
            if entry.depth >= depth {
                let score = score_from_tt(entry.score, ply);
                match entry.bound {
                    Bound::Exact => return score,
                    Bound::Lower if score >= beta => return score,
                    Bound::Upper if score <= alpha => return score,
                    Bound::Lower | Bound::Upper => {}
                }
            }
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return score;
        }
        if depth == 0 {
            let score = evaluate(position);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return score;
        }

        let hint = table_entry.and_then(|entry| entry.best_move);
        let mut best = -INFINITY;
        let mut best_move = None;

        for mv in OrderedMoves::new(&moves, hint) {
            let undo = position.make_move(mv);
            let score = -self.negamax(position, depth - 1, -beta, -alpha, ply + 1);
            position.unmake_move(mv, undo);

            if score > best {
                best = score;
                best_move = Some(mv);
            }
            alpha = alpha.max(score);
            if alpha >= beta {
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
        best
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

struct OrderedMoves<'a> {
    moves: &'a [ChessMove],
    hint: Option<ChessMove>,
    phase: u8,
    index: usize,
}

impl<'a> OrderedMoves<'a> {
    fn new(moves: &'a MoveList, hint: Option<ChessMove>) -> Self {
        Self {
            moves: moves.as_slice(),
            hint,
            phase: 0,
            index: 0,
        }
    }
}

impl Iterator for OrderedMoves<'_> {
    type Item = ChessMove;

    fn next(&mut self) -> Option<Self::Item> {
        loop {
            match self.phase {
                0 => {
                    self.phase = 1;
                    if let Some(hint) = self.hint {
                        if self.moves.contains(&hint) {
                            return Some(hint);
                        }
                    }
                }
                1 | 2 => {
                    while self.index < self.moves.len() {
                        let mv = self.moves[self.index];
                        self.index += 1;
                        if Some(mv) == self.hint {
                            continue;
                        }
                        let tactical = mv.kind().is_capture() || mv.kind().is_promotion();
                        if tactical == (self.phase == 1) {
                            return Some(mv);
                        }
                    }
                    self.phase += 1;
                    self.index = 0;
                }
                _ => return None,
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use chess_core::{Color, Position};

    use super::{
        MATE_SCORE, Searcher, iterative_deepening, score_from_tt, score_to_tt, search, search_mut,
    };

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
