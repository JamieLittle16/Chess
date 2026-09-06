#!/usr/bin/env python3
"""Apply the M4 killer-move v1 implementation deterministically."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_first(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count < 1:
        raise SystemExit(f"{label}: expected at least one match, found {count}")
    return text.replace(old, new, 1)


picker_path = Path("crates/chess-search/src/move_picker.rs")
picker = picker_path.read_text()
picker = replace_once(picker, "enum Stage {\n    Tt,\n    Tactical,\n    Quiet,\n    Done,\n}", "enum Stage {\n    Tt,\n    Tactical,\n    Killer,\n    Quiet,\n    Done,\n}", "picker stage")
picker = replace_once(picker, "    tt_move: Option<ChessMove>,\n    stage: Stage,\n    cursor: usize,\n}", "    tt_move: Option<ChessMove>,\n    killers: [Option<ChessMove>; 2],\n    killer_index: usize,\n    stage: Stage,\n    cursor: usize,\n}", "picker fields")
picker = replace_once(picker, "    pub(super) fn new(moves: &'a mut MoveList, tt_move: Option<ChessMove>) -> Self {\n        Self {\n            moves: moves.as_mut_slice(),\n            tt_move,\n            stage: Stage::Tt,\n            cursor: 0,\n        }\n    }", "    pub(super) fn new(\n        moves: &'a mut MoveList,\n        tt_move: Option<ChessMove>,\n        killers: [Option<ChessMove>; 2],\n    ) -> Self {\n        Self {\n            moves: moves.as_mut_slice(),\n            tt_move,\n            killers,\n            killer_index: 0,\n            stage: Stage::Tt,\n            cursor: 0,\n        }\n    }", "picker constructor")
picker = replace_once(picker, "                    self.stage = Stage::Quiet;\n                }\n                Stage::Quiet => {", "                    self.stage = Stage::Killer;\n                }\n                Stage::Killer => {\n                    while self.killer_index < self.killers.len() {\n                        let killer = self.killers[self.killer_index];\n                        self.killer_index += 1;\n                        if let Some(killer) = killer\n                            && !is_tactical(killer)\n                            && let Some(index) = self.moves[self.cursor..]\n                                .iter()\n                                .position(|&mv| mv == killer)\n                                .map(|offset| self.cursor + offset)\n                        {\n                            self.moves.swap(self.cursor, index);\n                            let mv = self.moves[self.cursor];\n                            self.cursor += 1;\n                            return Some(mv);\n                        }\n                    }\n                    self.stage = Stage::Quiet;\n                }\n                Stage::Quiet => {", "killer stage")
picker = picker.replace("MovePicker::new(&mut moves, Some(tt_move))", "MovePicker::new(&mut moves, Some(tt_move), [None; 2])")
picker = picker.replace("MovePicker::new(&mut moves, None)", "MovePicker::new(&mut moves, None, [None; 2])")
picker = picker.replace("MovePicker::new(&mut scratch, Some(original.as_slice()[3]))", "MovePicker::new(&mut scratch, Some(original.as_slice()[3]), [None; 2])")
picker = replace_once(picker, "    #[test]\n    fn every_legal_move_is_returned_exactly_once() {", "    #[test]\n    fn quiet_killer_is_emitted_before_generator_order_quiets() {\n        let position = Position::startpos();\n        let original = position.legal_moves();\n        let killer = original.as_slice()[original.len() - 1];\n        let mut moves = original.clone();\n        let mut picker = MovePicker::new(&mut moves, None, [Some(killer), None]);\n\n        assert_eq!(picker.next(&position), Some(killer));\n    }\n\n    #[test]\n    fn every_legal_move_is_returned_exactly_once() {", "killer test")
picker_path.write_text(picker)

search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(search, "    path_keys: [u64; MAX_SEARCH_PLY],\n}", "    path_keys: [u64; MAX_SEARCH_PLY],\n    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n}", "searcher fields")
search = replace_once(search, "            path_keys: [0; MAX_SEARCH_PLY],\n        }", "            path_keys: [0; MAX_SEARCH_PLY],\n            killers: [[None; 2]; MAX_SEARCH_PLY],\n        }", "searcher constructor")
search = replace_once(search, "        self.nodes = 1;\n        self.tt_hits = 0;", "        self.nodes = 1;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];", "exact-search reset")
search = replace_once(search, "        self.nodes = 0;\n        self.tt_hits = 0;\n        let mut last_completed = None;", "        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        let mut last_completed = None;", "iterative reset")
search = replace_first(search, "        let mut picker = MovePicker::new(&mut moves, hint);\n        let mut first_move = true;", "        let mut picker = MovePicker::new(&mut moves, hint, [None; 2]);\n        let mut first_move = true;", "root picker")
search = replace_once(search, "        let mut moves = moves;\n        let mut picker = MovePicker::new(&mut moves, hint);\n        let mut first_move = true;", "        let mut moves = moves;\n        let killers = self.killers[usize::from(ply)];\n        let mut picker = MovePicker::new(&mut moves, hint, killers);\n        let mut first_move = true;", "recursive picker")
search = replace_once(search, "            if alpha >= beta {\n                break;\n            }", "            if alpha >= beta {\n                if !mv.kind().is_capture() && !mv.kind().is_promotion() {\n                    let killers = &mut self.killers[usize::from(ply)];\n                    if killers[0] != Some(mv) {\n                        killers[1] = killers[0];\n                        killers[0] = Some(mv);\n                    }\n                }\n                break;\n            }", "killer recording")
search_path.write_text(search)

qsearch_path = Path("crates/chess-search/src/quiescence.rs")
qsearch = qsearch_path.read_text()
qsearch = replace_once(qsearch, "MovePicker::new(&mut moves, None)", "MovePicker::new(&mut moves, None, [None; 2])", "qsearch picker")
qsearch_path.write_text(qsearch)
