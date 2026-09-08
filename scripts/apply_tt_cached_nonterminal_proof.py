#!/usr/bin/env python3
"""Use a resident TT static evaluation as a proof that the exact position is nonterminal.

Precondition: scripts/apply_tt_static_eval_cache.py has already been applied.

A cached static evaluation can only be created after `has_legal_move_mut` succeeds on an RFP-eligible
node, or after a completed node with a non-empty legal move list is stored. Terminal paths return
before `record_static_eval`. The cache is keyed by the full search Zobrist identity; clocks are not
part of that key, but clocks cannot change move legality. Therefore `static_eval.is_some()` is also a
certificate that the exact board/state has at least one legal move, and the repeated existence probe
can be skipped on cache hits without changing chess semantics.
"""

from pathlib import Path


def main() -> int:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    old = """        let pruning_static_eval = if pruning_eligible {
            if !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            let static_eval = cached_static_eval.unwrap_or_else(|| self.leaf_evaluate(position));
            if cached_static_eval.is_none() {
                self.table.record_static_eval(key, static_eval);
            }
            Some(static_eval)
        } else {
            None
        };
"""
    new = """        let pruning_static_eval = if pruning_eligible {
            // `Some(static_eval)` is stronger than an evaluator cache hit: by construction it was
            // recorded only after this exact Zobrist position was proven to have a legal move.
            // Terminal paths never manufacture a cached evaluation, so a hit can safely reuse the
            // nonterminal proof and avoid repeating `has_legal_move_mut`.
            if cached_static_eval.is_none() && !has_legal_move_mut(position) {
                let score = terminal_score(position, ply);
                self.table
                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);
                return Some(score);
            }
            let static_eval = cached_static_eval.unwrap_or_else(|| self.leaf_evaluate(position));
            if cached_static_eval.is_none() {
                self.table.record_static_eval(key, static_eval);
            }
            Some(static_eval)
        } else {
            None
        };
"""
    if text.count(old) != 1:
        raise RuntimeError(f"expected basic TT cache RFP block once, found {text.count(old)}")
    text = text.replace(old, new)

    marker = """    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
"""
    invariant_test = """    #[test]
    fn terminal_search_entry_never_manufactures_static_eval_certificate() {
        let mut searcher = super::Searcher::with_tt_entries(64);
        let mut position = Position::from_fen(
            \"7k/6Q1/5K2/8/8/8/8/8 b - - 0 1\",
        )
        .expect(\"valid checkmated position\");
        let key = position.zobrist_key().raw();
        let score = searcher
            .negamax(&mut position, &[], 2, -super::INFINITY, super::INFINITY, 0, 0, &super::NeverStop)
            .expect(\"uninterrupted terminal search\");
        assert!(score <= -super::MATE_TT_THRESHOLD);
        let entry = searcher.table.probe(key).expect(\"terminal entry stored\");
        assert!(entry.static_eval.is_none());
    }

    #[test]
    fn megabyte_tt_sizing_matches_entry_layout_and_never_returns_zero() {
"""
    if text.count(marker) != 1:
        raise RuntimeError(f"expected TT sizing test marker once, found {text.count(marker)}")
    text = text.replace(marker, invariant_test)

    path.write_text(text, encoding="utf-8")
    print("applied TT cached-nonterminal proof candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
