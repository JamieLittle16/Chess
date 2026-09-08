#!/usr/bin/env python3
"""Materialize V15 qsearch check-evasion ceiling fix over accepted V14 production."""
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
    """        // Legal terminal detection happened above. The qsearch budget is local to this nominal leaf,
        // so a deep main search still receives the same tactical stabilization as a shallow search.
        if qply >= MAX_QSEARCH_PLY {
            return Some(self.leaf_evaluate(position));
        }
""",
    """        // Legal terminal detection happened above. The ordinary tactical budget remains local to
        // this nominal leaf, but it must never terminate a node while the side to move is in check.
        // At the ceiling we therefore resolve legal check evasions until the position becomes
        // non-check (or reaches the global search-ply guard), then allow stand-pat again. This fixes
        // the old horizon where a checked position with legal evasions could be statically scored.
        if qply >= MAX_QSEARCH_PLY && !in_check {
            return Some(self.leaf_evaluate(position));
        }
""",
    "qsearch in-check ceiling",
)

text = replace_once(
    text,
    """    #[test]
    fn qsearch_local_ceiling_is_bounded_and_restores_position() {
        let mut position =
            Position::from_fen("4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1").expect("valid FEN");
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence_inner(
                &mut position,
                &[],
                -INFINITY,
                INFINITY,
                23,
                23,
                MAX_QSEARCH_PLY,
                &NeverStop,
            )
            .expect("bounded quiescence completes");
        assert_eq!(score, evaluate(&position));
        assert_eq!(searcher.nodes, 1);
        assert_eq!(position, original);
    }
""",
    """    #[test]
    fn qsearch_local_ceiling_still_resolves_check_and_restores_position() {
        let mut position =
            Position::from_fen("4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1").expect("valid FEN");
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let _score = searcher
            .quiescence_inner(
                &mut position,
                &[],
                -INFINITY,
                INFINITY,
                23,
                23,
                MAX_QSEARCH_PLY,
                &NeverStop,
            )
            .expect("check-evasion quiescence completes");
        assert!(searcher.nodes > 1, "the local ceiling cannot stand-pat in check");
        assert_eq!(position, original);
    }

    #[test]
    fn qsearch_local_ceiling_still_stops_a_non_check_leaf() {
        let mut position = Position::startpos();
        let original = position.clone();
        let mut searcher = Searcher {
            nodes: 1,
            ..Searcher::default()
        };
        let score = searcher
            .quiescence_inner(
                &mut position,
                &[],
                -INFINITY,
                INFINITY,
                23,
                23,
                MAX_QSEARCH_PLY,
                &NeverStop,
            )
            .expect("bounded quiet quiescence completes");
        assert_eq!(score, evaluate(&position));
        assert_eq!(searcher.nodes, 1);
        assert_eq!(position, original);
    }
""",
    "qsearch ceiling regression",
)

path.write_text(text)
print("applied V15 qsearch check-evasion ceiling fix")
