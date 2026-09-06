#!/usr/bin/env python3
"""Apply a four-way clustered transposition-table replacement policy."""
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
    "//! negamax/alpha-beta search with deterministic move ordering and a bounded direct-mapped\n//! transposition table. It is the control group for later tactical and strategic search research.",
    "//! negamax/alpha-beta search with deterministic move ordering and a bounded clustered\n//! transposition table. It is the control group for later tactical and strategic search research.",
    "module docs",
)
text = replace_once(
    text,
    "const MAX_SEARCH_PLY: usize = 256;",
    "const MAX_SEARCH_PLY: usize = 256;\nconst TT_CLUSTER_SIZE: usize = 4;",
    "cluster size",
)
old_impl = '''    fn probe(&self, key: u64) -> Option<TtEntry> {
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
    }'''
new_impl = '''    fn probe(&self, key: u64) -> Option<TtEntry> {
        let (start, width) = self.cluster(key)?;
        self.entries[start..start + width]
            .iter()
            .copied()
            .find(|entry| entry.valid && entry.key == key)
    }

    fn store(
        &mut self,
        key: u64,
        depth: u8,
        score: i32,
        bound: Bound,
        best_move: Option<ChessMove>,
    ) {
        let Some((start, width)) = self.cluster(key) else {
            return;
        };
        let cluster = &self.entries[start..start + width];

        let slot = if let Some(offset) = cluster
            .iter()
            .position(|entry| entry.valid && entry.key == key)
        {
            let slot = start + offset;
            if depth < self.entries[slot].depth {
                return;
            }
            slot
        } else if let Some(offset) = cluster.iter().position(|entry| !entry.valid) {
            start + offset
        } else {
            let offset = cluster
                .iter()
                .enumerate()
                .min_by_key(|(offset, entry)| (entry.depth, *offset))
                .map(|(offset, _)| offset)
                .expect("a non-empty full cluster has a replacement slot");
            start + offset
        };

        self.entries[slot] = TtEntry {
            valid: true,
            key,
            depth,
            score,
            bound,
            best_move,
        };
    }

    fn cluster(&self, key: u64) -> Option<(usize, usize)> {
        if self.entries.is_empty() {
            return None;
        }
        if self.entries.len() < TT_CLUSTER_SIZE {
            return Some((0, self.entries.len()));
        }
        let clusters = self.entries.len() / TT_CLUSTER_SIZE;
        let start = (key as usize % clusters) * TT_CLUSTER_SIZE;
        Some((start, TT_CLUSTER_SIZE))
    }'''
text = replace_once(text, old_impl, new_impl, "TT implementation")
text = replace_once(
    text,
    "        score_from_tt, score_to_tt, search, search_mut, tt_entries_for_megabytes,\n    };",
    "        Bound, TranspositionTable, MATE_SCORE, SearchControl, Searcher,\n        has_two_prior_occurrences, iterative_deepening, score_from_tt, score_to_tt, search,\n        search_mut, tt_entries_for_megabytes,\n    };",
    "test imports",
)
text = replace_once(
    text,
    "    #[test]\n    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {",
    '''    #[test]
    fn clustered_tt_preserves_deep_entries_across_collisions() {
        let mut table = TranspositionTable::new(8);
        for (key, depth) in [(0_u64, 8_u8), (2, 7), (4, 6), (6, 5)] {
            table.store(key, depth, i32::from(depth), Bound::Exact, None);
        }
        table.store(8, 1, 1, Bound::Exact, None);

        assert_eq!(table.probe(0).expect("deep colliding entry survives").depth, 8);
        assert_eq!(table.probe(8).expect("new colliding entry is admitted").depth, 1);

        table.store(0, 3, 3, Bound::Exact, None);
        assert_eq!(
            table.probe(0).expect("shallower same-key store is ignored").depth,
            8
        );
    }

    #[test]
    fn tiny_tt_capacity_remains_supported() {
        let mut table = TranspositionTable::new(1);
        table.store(11, 2, 5, Bound::Exact, None);
        assert_eq!(table.probe(11).expect("single-slot table works").score, 5);
    }

    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {''',
    "cluster tests",
)
path.write_text(text)
