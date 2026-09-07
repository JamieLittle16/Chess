#!/usr/bin/env python3
"""Apply inline legality filtering so searched legal moves are made only once."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_count(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count != expected:
        raise SystemExit(f"{label}: expected {expected} matches, found {count}")
    return text.replace(old, new)


# chess-core: expose the existing pseudo-legal buffer as an explicit search substrate.
path = Path("crates/chess-core/src/movegen.rs")
text = path.read_text()
text = replace_once(
    text,
    '''fn generate_pseudo_legal_moves(position: &Position) -> MoveList {
    let mut moves = MoveList::new();''',
    '''/// Generate structurally valid candidate moves without testing final king safety.
///
/// This is a search-facing substrate for callers that can make a candidate, reject it when the
/// moving side remains in check, and reuse that already-made position when it is legal. Ordinary
/// clients should continue to use [`generate_legal_moves`] or [`generate_legal_moves_mut`].
#[must_use]
pub fn generate_pseudo_legal_moves(position: &Position) -> MoveList {
    let mut moves = MoveList::new();''',
    "expose pseudo legal generator",
)
path.write_text(text)

path = Path("crates/chess-core/src/lib.rs")
text = path.read_text()
text = replace_once(
    text,
    '''pub use movegen::{
    generate_legal_moves, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
    has_legal_move_mut,
};''',
    '''pub use movegen::{
    generate_legal_moves, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
    generate_pseudo_legal_moves, has_legal_move_mut,
};''',
    "export pseudo legal generator",
)
path.write_text(text)

# MovePicker: add an applied-move path that removes illegal candidates while preserving the order of
# all still-unexamined candidates. Legal candidates are returned with their Undo and remain made.
path = Path("crates/chess-search/src/move_picker.rs")
text = path.read_text()
text = replace_once(
    text,
    'use chess_core::{ChessMove, MoveKind, MoveList, Position};',
    'use chess_core::{ChessMove, MoveKind, MoveList, Position, Undo};',
    "move picker Undo import",
)
text = replace_once(
    text,
    '''pub(super) struct MovePicker<'a> {
    moves: &'a mut [ChessMove],
    tt_move: Option<ChessMove>,''',
    '''pub(super) struct MovePicker<'a> {
    moves: &'a mut [ChessMove],
    active_len: usize,
    tt_move: Option<ChessMove>,''',
    "move picker active length",
)
text = replace_once(
    text,
    '''    ) -> Self {
        Self {
            moves: moves.as_mut_slice(),
            tt_move,''',
    '''    ) -> Self {
        let active_len = moves.len();
        Self {
            moves: moves.as_mut_slice(),
            active_len,
            tt_move,''',
    "move picker constructor",
)
text = replace_count(
    text,
    'self.moves[self.cursor..]',
    'self.moves[self.cursor..self.active_len]',
    2,
    "bounded TT/killer scans",
)
text = replace_once(
    text,
    'for index in self.cursor..self.moves.len() {',
    'for index in self.cursor..self.active_len {',
    "bounded tactical scan",
)
text = replace_once(
    text,
    'if self.cursor < self.moves.len() {',
    'if self.cursor < self.active_len {',
    "bounded quiet scan",
)
text = replace_once(
    text,
    '''    }
}

fn is_tactical(mv: ChessMove) -> bool {''',
    '''    }

    /// Select the next legal move and leave it applied to `position`.
    ///
    /// The input buffer may contain pseudo-legal candidates. Illegal candidates are made only long
    /// enough to test king safety, then unmade and removed without changing the relative order of
    /// the remaining candidates. A legal candidate is returned together with its undo record while
    /// the board remains in the child position, allowing search to recurse immediately instead of
    /// repeating the same make after an eager legality-filter pass.
    pub(super) fn next_legal_applied(
        &mut self,
        position: &mut Position,
    ) -> Option<(ChessMove, Undo)> {
        loop {
            match self.stage {
                Stage::Tt => {
                    self.stage = Stage::Tactical;
                    if let Some(tt_move) = self.tt_move
                        && let Some(index) = self.moves[self.cursor..self.active_len]
                            .iter()
                            .position(|&mv| mv == tt_move)
                            .map(|offset| self.cursor + offset)
                        && let Some(applied) = self.try_apply_candidate(position, index)
                    {
                        return Some(applied);
                    }
                }
                Stage::Tactical => {
                    let mut best_index = None;
                    let mut best_score = i32::MIN;
                    for index in self.cursor..self.active_len {
                        let mv = self.moves[index];
                        if !is_tactical(mv) {
                            continue;
                        }
                        let score = tactical_score(position, mv);
                        if score > best_score {
                            best_score = score;
                            best_index = Some(index);
                        }
                    }

                    if let Some(index) = best_index {
                        if let Some(applied) = self.try_apply_candidate(position, index) {
                            return Some(applied);
                        }
                        continue;
                    }
                    self.stage = Stage::Killer;
                }
                Stage::Killer => {
                    while self.killer_index < self.killers.len() {
                        let killer = self.killers[self.killer_index];
                        self.killer_index += 1;
                        if let Some(killer) = killer
                            && !is_tactical(killer)
                            && let Some(index) = self.moves[self.cursor..self.active_len]
                                .iter()
                                .position(|&mv| mv == killer)
                                .map(|offset| self.cursor + offset)
                        {
                            if let Some(applied) = self.try_apply_candidate(position, index) {
                                return Some(applied);
                            }
                            break;
                        }
                    }
                    if self.killer_index >= self.killers.len() {
                        self.stage = Stage::Quiet;
                    }
                }
                Stage::Quiet => {
                    if self.cursor < self.active_len {
                        if let Some(applied) = self.try_apply_candidate(position, self.cursor) {
                            return Some(applied);
                        }
                        continue;
                    }
                    self.stage = Stage::Done;
                }
                Stage::Done => return None,
            }
        }
    }

    fn try_apply_candidate(
        &mut self,
        position: &mut Position,
        index: usize,
    ) -> Option<(ChessMove, Undo)> {
        let mv = self.moves[index];
        let us = position.side_to_move();
        let undo = position.make_move(mv);
        if position.is_in_check(us) {
            position.unmake_move(mv, undo);
            self.remove_candidate_preserving_order(index);
            return None;
        }

        self.moves.swap(self.cursor, index);
        self.cursor += 1;
        Some((mv, undo))
    }

    fn remove_candidate_preserving_order(&mut self, index: usize) {
        debug_assert!(index >= self.cursor);
        debug_assert!(index < self.active_len);
        self.moves.copy_within(index + 1..self.active_len, index);
        self.active_len -= 1;
    }
}

fn is_tactical(mv: ChessMove) -> bool {''',
    "applied legal picker",
)
text = replace_once(
    text,
    '''mod tests {
    use chess_core::{Position, Square};''',
    '''mod tests {
    use chess_core::{Position, Square, generate_pseudo_legal_moves};''',
    "move picker test imports",
)
text = replace_once(
    text,
    '''    #[test]
    fn every_legal_move_is_returned_exactly_once() {''',
    '''    #[test]
    fn applied_picker_rejects_illegal_candidates_and_restores_after_unmake() {
        let fens = [
            chess_core::STARTPOS_FEN,
            "k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1",
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        ];

        for fen in fens {
            let mut position = Position::from_fen(fen).expect("valid picker FEN");
            let root = position.clone();
            let mut expected: Vec<_> = root.legal_moves().as_slice().to_vec();
            let mut candidates = generate_pseudo_legal_moves(&position);
            let mut picker = MovePicker::new(&mut candidates, None, [None; 2]);
            let mut actual = Vec::with_capacity(expected.len());

            while let Some((mv, undo)) = picker.next_legal_applied(&mut position) {
                actual.push(mv);
                position.unmake_move(mv, undo);
                assert_eq!(position, root, "applied picker must restore {fen} after caller unmake");
            }

            expected.sort_unstable_by_key(|mv| mv.raw());
            actual.sort_unstable_by_key(|mv| mv.raw());
            assert_eq!(actual, expected, "applied picker legal-set mismatch for {fen}");
            assert_eq!(position, root);
        }
    }

    #[test]
    fn every_legal_move_is_returned_exactly_once() {''',
    "applied picker regression",
)
path.write_text(text)

# Search: use the pseudo buffer only on ordinary full-search nodes. Root draw handling, fallback,
# qsearch and the RFP early-existence probe remain on their existing legal APIs.
path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()
text = replace_once(
    text,
    '''use chess_core::{ChessMove, PieceKind, Position, generate_legal_moves_mut, has_legal_move_mut};''',
    '''use chess_core::{
    ChessMove, PieceKind, Position, generate_legal_moves_mut, generate_pseudo_legal_moves,
    has_legal_move_mut,
};''',
    "search pseudo generator import",
)
text = replace_once(
    text,
    '''        let moves = generate_legal_moves_mut(position);
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
''',
    '''        if depth == 0 {
            let moves = generate_legal_moves_mut(position);
            if moves.is_empty() {
                let score = terminal_score(position, 0);
                self.table
                    .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
                return Some(self.result(None, score, depth));
            }
            let score = evaluate(position);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return Some(self.result(None, score, depth));
        }

        let moves = generate_pseudo_legal_moves(position);
        if moves.is_empty() {
            let score = terminal_score(position, 0);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return Some(self.result(None, score, depth));
        }
''',
    "root pseudo move generation",
)
text = replace_count(
    text,
    '''while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);''',
    '''while let Some((mv, undo)) = picker.next_legal_applied(position) {''',
    2,
    "applied root and recursive picker loops",
)
text = replace_once(
    text,
    '''        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            Bound::Exact,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))''',
    '''        if best_move.is_none() {
            let score = terminal_score(position, 0);
            self.table
                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);
            return Some(self.result(None, score, depth));
        }

        self.table.store(
            key,
            depth,
            score_to_tt(best_score, 0),
            Bound::Exact,
            best_move,
        );
        Some(self.result(best_move, best_score, depth))''',
    "root all-illegal terminal",
)
text = replace_once(
    text,
    '''        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);''',
    '''        let moves = generate_pseudo_legal_moves(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);''',
    "recursive pseudo move generation",
)
text = replace_once(
    text,
    '''        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };''',
    '''        if best_move.is_none() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        let bound = if best <= alpha_original {
            Bound::Upper
        } else if best >= beta {
            Bound::Lower
        } else {
            Bound::Exact
        };''',
    "recursive all-illegal terminal",
)
path.write_text(text)
