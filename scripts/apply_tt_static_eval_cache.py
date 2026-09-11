#!/usr/bin/env python3
"""Add a semantics-preserving TT static-evaluation cache for V16 qualification.

The experiment stores only exact evaluator outputs for an already-matching TT key. It never creates
partial search entries, never changes bound/depth replacement policy, and keeps the legal-move probe
before reverse-futility pruning. The cached value is deliberately i16-sized so it can occupy existing
TT padding; out-of-range evaluator scores are simply not cached.
"""

from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new)


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """struct TtEntry {
    valid: bool,
    key: u64,
    depth: u8,
    score: i32,
    bound: Bound,
    best_move: Option<ChessMove>,
}
""",
        """struct TtEntry {
    valid: bool,
    key: u64,
    depth: u8,
    score: i32,
    bound: Bound,
    best_move: Option<ChessMove>,
    static_eval: Option<i16>,
}
""",
        count=1,
        label="TT entry field",
    )

    text = replace_exact(
        text,
        """        bound: Bound::Exact,
        best_move: None,
    };
""",
        """        bound: Bound::Exact,
        best_move: None,
        static_eval: None,
    };
""",
        count=1,
        label="empty TT entry",
    )

    text = replace_exact(
        text,
        """        let old = self.entries[slot];
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
""",
        """        let old = self.entries[slot];
        if !old.valid || old.key != key || depth >= old.depth {
            let static_eval = if old.valid && old.key == key {
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
                static_eval,
            };
        }
    }

    fn record_static_eval(&mut self, key: u64, eval: i32) {
        let Ok(eval) = i16::try_from(eval) else {
            return;
        };
        let Some(slot) = self.slot(key) else {
            return;
        };
        let entry = &mut self.entries[slot];
        if entry.valid && entry.key == key {
            entry.static_eval = Some(eval);
        }
    }

    fn slot(&self, key: u64) -> Option<usize> {
""",
        count=1,
        label="TT store/cache method",
    )

    text = replace_exact(
        text,
        """        let table_entry = self.probe(key);

        if let Some(entry) = table_entry
""",
        """        let table_entry = self.probe(key);
        let cached_static_eval = table_entry
            .and_then(|entry| entry.static_eval)
            .map(i32::from);

        if let Some(entry) = table_entry
""",
        count=1,
        label="cached TT eval probe",
    )

    text = replace_exact(
        text,
        """            Some(self.leaf_evaluate(position))
        } else {
            None
        };
""",
        """            let static_eval = cached_static_eval.unwrap_or_else(|| self.leaf_evaluate(position));
            if cached_static_eval.is_none() {
                self.table.record_static_eval(key, static_eval);
            }
            Some(static_eval)
        } else {
            None
        };
""",
        count=1,
        label="RFP static evaluation reuse",
    )

    text = replace_exact(
        text,
        """        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
        Some(best)
""",
        """        self.table
            .store(key, depth, score_to_tt(best, ply), bound, best_move);
        if let Some(static_eval) = pruning_static_eval {
            self.table.record_static_eval(key, static_eval);
        }
        Some(best)
""",
        count=1,
        label="attach eval after TT store",
    )

    text = replace_exact(
        text,
        """    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
        let expected = (1024 * 1024) / core::mem::size_of::<super::TtEntry>();
""",
        """    #[test]
    fn tt_static_eval_fits_existing_entry_padding_and_is_exactly_keyed() {
        assert_eq!(core::mem::size_of::<super::TtEntry>(), 24);
        let mut table = super::TranspositionTable::new(2);
        table.store(1, 3, 17, super::Bound::Exact, None);
        table.record_static_eval(1, 321);
        assert_eq!(table.probe(1).and_then(|entry| entry.static_eval), Some(321));

        // Key 3 aliases slot 1 in this two-entry table. A cache write for a colliding but absent
        // key must not corrupt the resident entry or create a partial TT record.
        table.record_static_eval(3, 777);
        assert_eq!(table.probe(1).and_then(|entry| entry.static_eval), Some(321));
        assert!(table.probe(3).is_none());
    }

    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
        let expected = (1024 * 1024) / core::mem::size_of::<super::TtEntry>();
""",
        count=1,
        label="TT cache invariant test",
    )

    path.write_text(text, encoding="utf-8")
    print("applied TT static-eval cache candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
