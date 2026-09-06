#!/usr/bin/env python3
"""Apply conservative non-checking capture delta pruning to qsearch."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/quiescence.rs")
text = path.read_text()
text = replace_once(
    text,
    "use chess_core::generate_legal_tactical_moves_mut;\n",
    "use chess_core::{MoveKind, generate_legal_tactical_moves_mut};\nuse chess_eval::PIECE_VALUES;\n",
    "delta imports",
)
text = replace_once(
    text,
    '''        let mut best = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };

        if !in_check {''',
    '''        let stand_pat = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };
        let mut best = stand_pat;

        if !in_check {''',
    "stand-pat binding",
)
text = replace_once(
    text,
    '''        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence_inner(''',
    '''        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        while let Some(mv) = picker.next(position) {
            // Delta pruning is deliberately conservative: promotions and in-check evasions are
            // never pruned, and a checking capture is retained even when its immediate material
            // gain cannot close the alpha gap. The generous margin covers ordinary PSQT/structure
            // swings without needing SEE or another evaluator pass.
            let optimistic_gain = if !in_check && mv.kind().is_capture() && !mv.kind().is_promotion()
            {
                if mv.kind() == MoveKind::EnPassant {
                    PIECE_VALUES[chess_core::PieceKind::Pawn.index()]
                } else {
                    position
                        .piece_at(mv.to())
                        .map_or(0, |piece| PIECE_VALUES[piece.kind().index()])
                }
            } else {
                0
            };
            let delta_candidate = !in_check
                && mv.kind().is_capture()
                && !mv.kind().is_promotion()
                && alpha < MATE_TT_THRESHOLD
                && stand_pat
                    .saturating_add(optimistic_gain)
                    .saturating_add(120)
                    <= alpha;

            let undo = position.make_move(mv);
            if delta_candidate && !position.is_in_check(position.side_to_move()) {
                position.unmake_move(mv, undo);
                continue;
            }
            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence_inner(''',
    "delta pruning loop",
)
path.write_text(text)
