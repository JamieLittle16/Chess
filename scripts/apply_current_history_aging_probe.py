#!/usr/bin/env python3
"""Isolate game-scoped History-v2 persistence on the current production stack."""

from __future__ import annotations

from pathlib import Path


def replace_count(path: Path, old: str, new: str, expected: int) -> None:
    text = path.read_text(encoding="utf-8")
    actual = text.count(old)
    if actual != expected:
        raise RuntimeError(
            f"{path}: expected {expected} occurrences of {old!r}, found {actual}"
        )
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> int:
    history = Path("crates/chess-search/src/history.rs")
    replace_count(
        history,
        """/// Search-local main + one-ply continuation history.\n///\n/// Tables are cleared once per top-level search, so iterative deepening can teach later iterations\n/// without making tournament games depend on earlier games in the same process. Storage is owned by\n/// `Searcher`; probes and updates allocate nothing in the recursive hot path.\n""",
        """/// Main + one-ply continuation history owned by one searcher.\n///\n/// Independent roots clear these tables. Engine frontends may explicitly retain them across a\n/// proven continuation of the same game; retained values are aged before the next root so stale\n/// preferences decay. Probes and updates allocate nothing in the recursive hot path.\n""",
        1,
    )
    replace_count(
        history,
        """    pub(super) fn clear(&mut self) {\n        self.main.fill(0);\n        self.continuation.fill(0);\n    }\n\n    #[must_use]\n    pub(super) fn score(""",
        """    pub(super) fn clear(&mut self) {\n        self.main.fill(0);\n        self.continuation.fill(0);\n    }\n\n    /// Decay retained same-game evidence before searching the next game root.\n    pub(super) fn age(&mut self) {\n        for entry in &mut self.main {\n            *entry = (i32::from(*entry) * 3 / 4) as i16;\n        }\n        for entry in &mut self.continuation {\n            *entry = (i32::from(*entry) * 3 / 4) as i16;\n        }\n    }\n\n    #[must_use]\n    pub(super) fn score(""",
        1,
    )

    search = Path("crates/chess-search/src/lib.rs")
    # Convert only the two existing independent-search root resets before adding the explicit
    # discard method below (which intentionally still calls HistoryTables::clear directly).
    replace_count(search, "self.history.clear();", "self.prepare_root_history();", 2)
    replace_count(
        search,
        """    history: HistoryTables,\n    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],\n""",
        """    history: HistoryTables,\n    preserve_history_once: bool,\n    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],\n""",
        1,
    )
    replace_count(
        search,
        """            history: HistoryTables::new(),\n            move_contexts: [None; MAX_SEARCH_PLY],\n""",
        """            history: HistoryTables::new(),\n            preserve_history_once: false,\n            move_contexts: [None; MAX_SEARCH_PLY],\n""",
        1,
    )
    replace_count(
        search,
        """    pub fn tt_capacity_entries(&self) -> usize {\n        self.table.len()\n    }\n\n    fn reset_leaf_evaluator""",
        """    pub fn tt_capacity_entries(&self) -> usize {\n        self.table.len()\n    }\n\n    /// Retain and age quiet-move history for exactly the next top-level root.\n    ///\n    /// This is deliberately explicit: raw `Searcher` reuse remains root-independent unless a\n    /// game-owning frontend has proved that the next root continues the same game.\n    pub fn preserve_move_history_for_next_root(&mut self) {\n        self.preserve_history_once = true;\n    }\n\n    /// Forget all quiet-move history and cancel any pending same-game retention request.\n    pub fn discard_move_history(&mut self) {\n        self.preserve_history_once = false;\n        self.history.clear();\n    }\n\n    fn prepare_root_history(&mut self) {\n        if std::mem::take(&mut self.preserve_history_once) {\n            self.history.age();\n        } else {\n            self.history.clear();\n        }\n    }\n\n    fn reset_leaf_evaluator""",
        1,
    )

    root_analysis = Path("crates/chess-search/src/root_analysis.rs")
    replace_count(
        root_analysis,
        "self.history.clear();",
        "self.discard_move_history();",
        1,
    )

    engine = Path("crates/chess-engine/src/lib.rs")
    replace_count(
        engine,
        """    pub fn set_position(&mut self, position: Position) {\n        self.repetition_history.clear();\n""",
        """    pub fn set_position(&mut self, position: Position) {\n        self.searcher.discard_move_history();\n        self.repetition_history.clear();\n""",
        1,
    )
    replace_count(
        engine,
        """    ) {\n        prior_history.push(position.repetition_key().raw());\n        self.position = position;\n        self.repetition_history = prior_history;\n    }\n\n    /// Start a fresh game""",
        """    ) {\n        prior_history.push(position.repetition_key().raw());\n        let continues_game = prior_history.len() > self.repetition_history.len()\n            && prior_history.starts_with(&self.repetition_history);\n        if continues_game {\n            self.searcher.preserve_move_history_for_next_root();\n        } else {\n            self.searcher.discard_move_history();\n        }\n        self.position = position;\n        self.repetition_history = prior_history;\n    }\n\n    /// Start a fresh game""",
        1,
    )
    replace_count(
        engine,
        """        self.repetition_history\n            .push(self.position.repetition_key().raw());\n        true\n""",
        """        self.repetition_history\n            .push(self.position.repetition_key().raw());\n        self.searcher.preserve_move_history_for_next_root();\n        true\n""",
        1,
    )

    print("applied game-scoped current-main history persistence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
