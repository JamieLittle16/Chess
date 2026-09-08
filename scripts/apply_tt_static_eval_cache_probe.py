#!/usr/bin/env python3
"""Apply a semantics-preserving TT static-evaluation cache experiment.

Only nodes that already own a normal search TT entry may carry a cached static evaluation. The
experiment never creates eval-only TT entries and never changes TT cutoffs, replacement depth,
move ordering, pruning margins, or search depth. It merely reuses an evaluator result when the same
Zobrist key is revisited and the node is eligible for V15 reverse/late-quiet futility logic.
"""

from __future__ import annotations

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    # Reuse a same-position static evaluation only after V15's existing legal-move safety probe.
    text = replace_exact(
        text,
        """            Some(self.leaf_evaluate(position))
        } else {
            None
        };""",
        """            Some(
                table_entry
                    .and_then(|entry| entry.static_eval)
                    .map(i32::from)
                    .unwrap_or_else(|| self.leaf_evaluate(position)),
            )
        } else {
            None
        };""",
        label="RFP static-eval reuse",
    )

    # Preserve an evaluation discovered at this node when the eventual search result enters the TT.
    text = replace_exact(
        text,
        """        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
""",
        """        self.table.store(
            key,
            depth,
            score_to_tt(best, ply),
            bound,
            best_move,
            pruning_static_eval,
        );
""",
        label="negamax TT store carries static eval",
    )

    # Root terminal/depth-zero stores have identical source syntax. Neither needs to seed this
    # experiment: the useful cache is learned at ordinary pruning-eligible negamax nodes.
    text = replace_exact(
        text,
        """                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None);""",
        """                .store(key, depth, score_to_tt(score, 0), Bound::Exact, None, None);""",
        count=2,
        label="root terminal/depth-zero stores",
    )

    # Every other store has no newly computed static eval. Same-key replacement still inherits one.
    store_calls = [
        (
            """            best_move,
        );
        Some(self.result(best_move, best_score, depth))""",
            """            best_move,
            None,
        );
        Some(self.result(best_move, best_score, depth))""",
            1,
            "root final store",
        ),
        (
            """                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);""",
            """                    .store(
                        key,
                        depth,
                        score_to_tt(score, ply),
                        Bound::Exact,
                        None,
                        None,
                    );""",
            1,
            "early terminal store",
        ),
        (
            """                .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);""",
            """                .store(
                    key,
                    depth,
                    score_to_tt(score, ply),
                    Bound::Exact,
                    None,
                    None,
                );""",
            1,
            "generated terminal store",
        ),
    ]
    for old, new, count, label in store_calls:
        text = replace_exact(text, old, new, count=count, label=label)

    text = replace_exact(
        text,
        """    score: i32,
    bound: Bound,
    best_move: Option<ChessMove>,
}""",
        """    score: i32,
    bound: Bound,
    best_move: Option<ChessMove>,
    static_eval: Option<i16>,
}""",
        label="TT static-eval field",
    )
    text = replace_exact(
        text,
        """        score: 0,
        bound: Bound::Exact,
        best_move: None,
    };""",
        """        score: 0,
        bound: Bound::Exact,
        best_move: None,
        static_eval: None,
    };""",
        label="empty TT static eval",
    )

    text = replace_exact(
        text,
        """        bound: Bound,
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
""",
        """        bound: Bound,
        best_move: Option<ChessMove>,
        static_eval: Option<i32>,
    ) {
        let Some(slot) = self.slot(key) else {
            return;
        };
        let old = self.entries[slot];
        if !old.valid || old.key != key || depth >= old.depth {
            let inherited_static_eval = if old.valid && old.key == key {
                old.static_eval
            } else {
                None
            };
            self.entries[slot] = TtEntry {
                valid: true,
                key,
                depth,
                score,
                bound,
                best_move,
                static_eval: static_eval.map(static_eval_to_tt).or(inherited_static_eval),
            };
        }
""",
        label="TT store static eval preservation",
    )

    text = replace_exact(
        text,
        """fn score_from_tt(score: i32, ply: u16) -> i32 {
""",
        """fn static_eval_to_tt(score: i32) -> i16 {
    score.clamp(i32::from(i16::MIN), i32::from(i16::MAX)) as i16
}

fn score_from_tt(score: i32, ply: u16) -> i32 {
""",
        label="static eval compression helper",
    )

    # Guard the main engineering premise: Option<i16> must consume existing layout slack, not shrink
    # the configured TT by increasing each entry.
    marker = """    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
"""
    text = replace_exact(
        text,
        marker,
        """    #[test]
    fn static_eval_cache_preserves_32_byte_tt_entry() {
        assert_eq!(core::mem::size_of::<super::TtEntry>(), 32);
    }

""" + marker,
        label="TT layout regression test",
    )

    path.write_text(text, encoding="utf-8")
    print("applied TT static-eval cache probe; search semantics and TT capacity guarded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
