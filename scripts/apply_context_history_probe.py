#!/usr/bin/env python3
"""Apply the M6 main + continuation history search experiment.

The committed substrate is semantics-neutral: ordinary MovePicker::next remains the accepted path.
This script activates the candidate policy only in qualification builds. Exact source-count checks make
source drift fail loudly rather than silently producing a partially active heuristic.
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


def patch_search() -> None:
    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """mod move_picker;
mod quiescence;
mod root_analysis;
""",
        """mod history;
mod move_picker;
mod quiescence;
mod root_analysis;
""",
        label="history module",
    )
    text = replace_exact(
        text,
        "use move_picker::MovePicker;",
        """use history::{HistoryTables, MoveContext, depth_bonus};
use move_picker::MovePicker;""",
        label="history imports",
    )

    text = replace_exact(
        text,
        """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
}""",
        """    path_keys: [u64; MAX_SEARCH_PLY],
    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],
    history: HistoryTables,
    move_contexts: [Option<MoveContext>; MAX_SEARCH_PLY],
}""",
        label="Searcher history fields",
    )
    text = replace_exact(
        text,
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
        }""",
        """            path_keys: [0; MAX_SEARCH_PLY],
            killers: [[None; 2]; MAX_SEARCH_PLY],
            history: HistoryTables::new(),
            move_contexts: [None; MAX_SEARCH_PLY],
        }""",
        label="Searcher history construction",
    )

    # Clear once per top-level search invocation, not once per iterative-deepening depth. This lets
    # earlier iterations teach later iterations but prevents cross-game process history.
    reset = """        self.nodes = 1;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
"""
    text = replace_exact(
        text,
        reset,
        reset + """        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
""",
        label="fixed-depth history reset",
    )
    iterative_reset = """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        let mut last_completed = None;
"""
    text = replace_exact(
        text,
        iterative_reset,
        """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
        let mut last_completed = None;
""",
        label="iterative history reset",
    )

    # Root ordering can consume main-history knowledge learned in earlier ID iterations. Root itself
    # has no predecessor context and is not used as a history-training node.
    root_picker = """        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
"""
    text = replace_exact(
        text,
        root_picker,
        """        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);
        let mut first_move = true;
        while let Some(mv) = picker.next_scored(position, |mv| {
            let context = move_context(position, mv);
            self.history.score(position.side_to_move(), None, context)
        }) {
            let context = move_context(position, mv);
            self.move_contexts[0] = Some(context);
            let undo = position.make_move(mv);
""",
        label="root history ordering",
    )

    picker = """        let mut moves = moves;
        let killers = self.killers[usize::from(ply)];
        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        let mut move_index = 0usize;
        while let Some(mv) = picker.next(position) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let undo = position.make_move(mv);
"""
    text = replace_exact(
        text,
        picker,
        """        let mut moves = moves;
        let killers = self.killers[usize::from(ply)];
        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        let mut move_index = 0usize;
        let previous_context = if ply == 0 {
            None
        } else {
            self.move_contexts[usize::from(ply - 1)]
        };
        while let Some(mv) = picker.next_scored(position, |mv| {
            let context = move_context(position, mv);
            self.history
                .score(position.side_to_move(), previous_context, context)
        }) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let side = position.side_to_move();
            let context = move_context(position, mv);
            self.move_contexts[usize::from(ply)] = Some(context);
            let undo = position.make_move(mv);
""",
        label="negamax history ordering",
    )

    score_site = """            let score = -child?;
            first_move = false;
            move_index = move_index.saturating_add(1);

            if score > best {
"""
    text = replace_exact(
        text,
        score_site,
        """            let score = -child?;
            first_move = false;
            move_index = move_index.saturating_add(1);

            // Train only on null-window/scout evidence. A quiet fail-high is a strong positive
            // ordering signal; a searched quiet that failed to cut gets a smaller gravity malus.
            // Full-window PV nodes do not train history, avoiding noisy value-based reinforcement.
            if quiet && null_window {
                let bonus = depth_bonus(depth);
                let update = if score >= beta { bonus } else { -(bonus / 2) };
                self.history
                    .update(side, previous_context, context, update);
            }

            if score > best {
""",
        label="scout history training",
    )

    helper_anchor = """fn has_reverse_futility_material(position: &Position) -> bool {
"""
    helper = """fn move_context(position: &Position, mv: ChessMove) -> MoveContext {
    let piece = position
        .piece_at(mv.from())
        .expect("generated legal move has a moving piece");
    MoveContext::new(piece.kind(), mv.to())
}

""" + helper_anchor
    text = replace_exact(text, helper_anchor, helper, label="move-context helper")

    path.write_text(text, encoding="utf-8")


def patch_root_analysis() -> None:
    path = Path("crates/chess-search/src/root_analysis.rs")
    text = path.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
""",
        """        self.nodes = 0;
        self.tt_hits = 0;
        self.killers = [[None; 2]; MAX_SEARCH_PLY];
        self.history.clear();
        self.move_contexts = [None; MAX_SEARCH_PLY];
""",
        label="root-analysis history reset",
    )
    text = replace_exact(
        text,
        """        for order in 0..moves.len() {
            let mv = moves[order];
            let undo = position.make_move(mv);
""",
        """        for order in 0..moves.len() {
            let mv = moves[order];
            self.move_contexts[0] = Some(super::move_context(position, mv));
            let undo = position.make_move(mv);
""",
        label="root-analysis predecessor context",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    patch_search()
    patch_root_analysis()
    print("applied M6 main + continuation history candidate")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
