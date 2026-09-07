#!/usr/bin/env python3
"""Apply conservative non-checking capture delta pruning in quiescence."""
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
    "use chess_core::generate_legal_tactical_moves_mut;\nuse chess_eval::PIECE_VALUES;\n",
    "piece values import",
)

text = replace_once(
    text,
    "const MAX_QSEARCH_PLY: usize = 4;",
    "const MAX_QSEARCH_PLY: usize = 4;\nconst DELTA_MARGIN: i32 = 120;",
    "delta margin",
)

text = replace_once(
    text,
    '''        let mut best = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };''',
    '''        let stand_pat = if in_check {
            -INFINITY
        } else {
            evaluate(position)
        };
        let mut best = stand_pat;''',
    "stand pat binding",
)

text = replace_once(
    text,
    '''        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence_inner(''',
    '''        let mut picker = MovePicker::new(&mut moves, None, [None; 2]);
        while let Some(mv) = picker.next(position) {
            // Conservative delta pruning v1. Only ordinary captures with a real destination victim
            // are eligible, which excludes promotions and en-passant. We make the move before the
            // decision so checking captures are never pruned. The margin is deliberately generous;
            // if even stand-pat plus the full victim value and margin cannot reach alpha, a quiet
            // non-checking capture is extremely unlikely to matter to this qsearch window.
            let victim_value = if !in_check
                && mv.kind().is_capture()
                && !mv.kind().is_promotion()
                && beta.abs() < MATE_TT_THRESHOLD
            {
                position
                    .piece_at(mv.to())
                    .map(|piece| PIECE_VALUES[piece.kind().index()])
            } else {
                None
            };
            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            if let Some(victim_value) = victim_value
                && !gives_check
                && stand_pat
                    .saturating_add(victim_value)
                    .saturating_add(DELTA_MARGIN)
                    < alpha
            {
                position.unmake_move(mv, undo);
                continue;
            }

            self.nodes = self.nodes.saturating_add(1);
            let child = self.quiescence_inner(''',
    "delta pruning loop",
)

text = replace_once(
    text,
    '''    #[test]
    fn quiet_stable_leaf_does_not_need_tactical_moves() {''',
    '''    #[test]
    fn delta_prunes_only_nonchecking_low_value_capture_below_alpha() {
        let mut quiet_capture =
            Position::from_fen("7k/p7/8/8/8/8/8/Q5K1 w - - 0 1").expect("valid FEN");
        let original = quiet_capture.clone();
        let stand_pat = evaluate(&quiet_capture);
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence_inner(
                &mut quiet_capture,
                &[],
                stand_pat + 300,
                stand_pat + 301,
                0,
                0,
                0,
                &NeverStop,
            )
            .expect("delta-pruned qsearch completes");
        assert_eq!(score, stand_pat);
        assert_eq!(searcher.nodes, 1, "pruned capture does not recurse");
        assert_eq!(quiet_capture, original);

        let mut checking_capture =
            Position::from_fen("8/p6k/8/8/8/8/8/Q5K1 w - - 0 1").expect("valid FEN");
        let stand_pat = evaluate(&checking_capture);
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let _ = searcher
            .quiescence_inner(
                &mut checking_capture,
                &[],
                stand_pat + 300,
                stand_pat + 301,
                0,
                0,
                0,
                &NeverStop,
            )
            .expect("checking capture remains searchable");
        assert!(searcher.nodes > 1, "checking capture must not be delta-pruned");
    }

    #[test]
    fn quiet_stable_leaf_does_not_need_tactical_moves() {''',
    "delta tests",
)

path.write_text(text)
