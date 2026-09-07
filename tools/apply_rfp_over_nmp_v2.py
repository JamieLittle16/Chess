#!/usr/bin/env python3
"""Add conservative RFP v1 to an already-materialized draw-safe NMP v2 search."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

# Reuse NMP's single real-node static evaluation. RFP is deliberately disabled in both synthetic
# null subtrees and the NO_NULL verification search: the former have synthetic draw/TT semantics,
# while the latter must remain a genuine verification of a marginal deep null fail-high.
text = replace_once(
    text,
    '''        let static_eval = if mode.allow_null && !mode.synthetic && !in_check {
            Some(evaluate(position))
        } else {
            None
        };
        if mode.allow_null''',
    '''        let static_eval = if mode.allow_null && !mode.synthetic && !in_check {
            Some(evaluate(position))
        } else {
            None
        };

        // RFP v1, composed only at ordinary real nodes. Legal terminal detection has already run.
        // Keeping this out of synthetic/null-verification modes preserves NMP v2's safety contract.
        if mode.allow_null
            && !mode.synthetic
            && depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position)
        {
            let static_eval = static_eval.expect("real pruning node computed static evaluation");
            let margin = 120 * i32::from(depth);
            if static_eval.saturating_sub(margin) >= beta {
                return Some(static_eval);
            }
        }

        if mode.allow_null''',
    "real-node RFP gate",
)

text = replace_once(
    text,
    "fn has_null_move_material(position: &Position) -> bool {",
    '''fn has_reverse_futility_material(position: &Position) -> bool {
    let us = position.side_to_move();
    !(position.pieces(us, PieceKind::Knight)
        | position.pieces(us, PieceKind::Bishop)
        | position.pieces(us, PieceKind::Rook)
        | position.pieces(us, PieceKind::Queen))
        .is_empty()
}

fn has_null_move_material(position: &Position) -> bool {''',
    "RFP material guard",
)

path.write_text(text)
