#!/usr/bin/env python3
"""Apply a semantics-neutral early legal-move existence probe before RFP."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Core move generation: expose an early-exit legal-existence query that uses the same pseudo move
# order and exact make/unmake legality test as the full generator, but stops after the first legal
# move instead of constructing/filtering the complete legal list.
movegen_path = Path("crates/chess-core/src/movegen.rs")
movegen = movegen_path.read_text()
movegen = replace_once(
    movegen,
    '''pub fn generate_legal_moves_mut(position: &mut Position) -> MoveList {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return MoveList::new();
    }

    let pseudo = generate_pseudo_legal_moves(position);
    filter_legal_moves(position, &pseudo, us)
}

/// Generate only legal captures, en-passant moves and promotions.''',
    '''pub fn generate_legal_moves_mut(position: &mut Position) -> MoveList {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return MoveList::new();
    }

    let pseudo = generate_pseudo_legal_moves(position);
    filter_legal_moves(position, &pseudo, us)
}

/// Return whether the side to move has at least one legal move, restoring `position` exactly.
///
/// This deliberately shares the ordinary pseudo-legal generator and make/unmake legality test, but
/// stops at the first legal move. Search uses it only on nodes that may be discarded by a static
/// pruning decision, where constructing and legality-filtering every move would otherwise be wasted.
#[must_use]
pub fn has_legal_move_mut(position: &mut Position) -> bool {
    let us = position.side_to_move();
    if position.king_square(us).is_none() {
        return false;
    }

    let pseudo = generate_pseudo_legal_moves(position);
    for &mv in &pseudo {
        let undo = position.make_move(mv);
        let is_legal = position
            .king_square(us)
            .is_some_and(|king| !is_square_attacked(position, king, us.opposite()));
        position.unmake_move(mv, undo);
        if is_legal {
            return true;
        }
    }
    false
}

/// Generate only legal captures, en-passant moves and promotions.''',
    "legal existence helper",
)
movegen = replace_once(
    movegen,
    '''    use crate::{MoveKind, Position, generate_legal_moves_mut, generate_legal_tactical_moves_mut};''',
    '''    use crate::{
        MoveKind, Position, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
        has_legal_move_mut,
    };''',
    "movegen test imports",
)
movegen = replace_once(
    movegen,
    '''    #[test]
    fn tactical_generator_matches_full_generator_filtered_to_tactical_moves() {''',
    '''    #[test]
    fn legal_existence_probe_matches_full_generation_and_restores_position() {
        let fens = [
            crate::STARTPOS_FEN,
            "7k/8/8/8/8/8/8/K7 w - - 0 1",
            "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
            "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
            "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        ];

        for fen in fens {
            let mut probe_position = Position::from_fen(fen).expect("valid probe FEN");
            let original = probe_position.clone();
            let mut full_position = original.clone();
            let expected = !generate_legal_moves_mut(&mut full_position).is_empty();
            assert_eq!(has_legal_move_mut(&mut probe_position), expected, "{fen}");
            assert_eq!(probe_position, original, "probe must restore {fen}");
            assert_eq!(full_position, original, "full generator must restore {fen}");
        }
    }

    #[test]
    fn tactical_generator_matches_full_generator_filtered_to_tactical_moves() {''',
    "legal existence tests",
)
movegen_path.write_text(movegen)

# Public core export.
core_lib_path = Path("crates/chess-core/src/lib.rs")
core_lib = core_lib_path.read_text()
core_lib = replace_once(
    core_lib,
    '''pub use movegen::{
    generate_legal_moves, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
};''',
    '''pub use movegen::{
    generate_legal_moves, generate_legal_moves_mut, generate_legal_tactical_moves_mut,
    has_legal_move_mut,
};''',
    "core export",
)
core_lib_path.write_text(core_lib)

# Search: only RFP-eligible nodes pay the existence probe. A successful RFP cutoff then avoids full
# legal generation entirely. When RFP does not cut, normal full generation, MovePicker order, LMR,
# LQF and TT behavior are unchanged.
search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(
    search,
    '''use chess_core::{ChessMove, PieceKind, Position, generate_legal_moves_mut};''',
    '''use chess_core::{
    ChessMove, PieceKind, Position, generate_legal_moves_mut, has_legal_move_mut,
};''',
    "search import",
)
search = replace_once(
    search,
    '''        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        // Accepted conservative reverse futility pruning v1. Terminal positions have already been
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
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);''',
    '''        // Accepted conservative reverse futility pruning v1. On eligible non-check scout
        // nodes, first prove that the position is nonterminal with an early-exit legal-move probe.
        // A successful RFP cutoff can then avoid constructing/filtering the complete legal list.
        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        let pruning_eligible = depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position);
        let pruning_static_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            Some(evaluate(position))
        } else {
            None
        };
        if let Some(static_eval) = pruning_static_eval {
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);''',
    "defer full legal generation past RFP",
)
search_path.write_text(search)
