#!/usr/bin/env python3
"""Apply a shallow, non-PV reverse-futility pruning experiment."""
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
    "use chess_core::{ChessMove, Position, generate_legal_moves_mut};",
    "use chess_core::{ChessMove, PieceKind, Position, generate_legal_moves_mut};",
    "piece-kind import",
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
    '''        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
            self.table
                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
            return Some(score);
        }

        // Conservative reverse futility pruning. Terminal positions have already been handled, and
        // only narrow-window shallow nodes are eligible. A generous depth-scaled margin plus a
        // non-pawn-material guard keeps this away from the most obvious zugzwang/endgame hazards.
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
        }

        debug_assert!(path_len < MAX_SEARCH_PLY);''',
    "reverse futility gate",
)

text = replace_once(
    text,
    "fn terminal_score(position: &Position, ply: u16) -> i32 {",
    '''fn has_reverse_futility_material(position: &Position) -> bool {
    let us = position.side_to_move();
    !(position.pieces(us, PieceKind::Knight)
        | position.pieces(us, PieceKind::Bishop)
        | position.pieces(us, PieceKind::Rook)
        | position.pieces(us, PieceKind::Queen))
        .is_empty()
}

fn terminal_score(position: &Position, ply: u16) -> i32 {''',
    "reverse futility material guard",
)

path.write_text(text)
