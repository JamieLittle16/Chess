#!/usr/bin/env python3
"""Apply one-slot countermove ordering after accepted killers."""
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
picker = replace_once(
    picker,
    "    Killer,\n    Quiet,",
    "    Killer,\n    Counter,\n    Quiet,",
    "counter stage enum",
)
picker = replace_once(
    picker,
    "    killers: [Option<ChessMove>; 2],\n    killer_index: usize,\n    stage: Stage,",
    "    killers: [Option<ChessMove>; 2],\n    countermove: Option<ChessMove>,\n    killer_index: usize,\n    stage: Stage,",
    "counter field",
)
picker = replace_once(
    picker,
    "        killers: [Option<ChessMove>; 2],\n    ) -> Self {",
    "        killers: [Option<ChessMove>; 2],\n        countermove: Option<ChessMove>,\n    ) -> Self {",
    "constructor arg",
)
picker = replace_once(
    picker,
    "            killers,\n            killer_index: 0,",
    "            killers,\n            countermove,\n            killer_index: 0,",
    "constructor field",
)
picker = replace_once(
    picker,
    "                    self.stage = Stage::Quiet;\n                }\n                Stage::Quiet => {",
    "                    self.stage = Stage::Counter;\n                }\n                Stage::Counter => {\n                    self.stage = Stage::Quiet;\n                    if let Some(countermove) = self.countermove\n                        && !is_tactical(countermove)\n                        && let Some(index) = self.moves[self.cursor..]\n                            .iter()\n                            .position(|&mv| mv == countermove)\n                            .map(|offset| self.cursor + offset)\n                    {\n                        self.moves.swap(self.cursor, index);\n                        let mv = self.moves[self.cursor];\n                        self.cursor += 1;\n                        return Some(mv);\n                    }\n                }\n                Stage::Quiet => {",
    "counter stage behavior",
)
picker = picker.replace("[None; 2]);", "[None; 2], None);")
picker = picker.replace("[Some(killer), None]);", "[Some(killer), None], None);")
picker = replace_once(
    picker,
    "    #[test]\n    fn every_legal_move_is_returned_exactly_once() {",
    '''    #[test]
    fn quiet_countermove_is_emitted_after_killers_before_ordinary_quiets() {
        let position = Position::startpos();
        let original = position.legal_moves();
        let killer = original.as_slice()[original.len() - 1];
        let countermove = original.as_slice()[original.len() - 2];
        let mut moves = original.clone();
        let mut picker = MovePicker::new(
            &mut moves,
            None,
            [Some(killer), None],
            Some(countermove),
        );

        assert_eq!(picker.next(&position), Some(killer));
        assert_eq!(picker.next(&position), Some(countermove));
    }

    #[test]
    fn every_legal_move_is_returned_exactly_once() {''',
    "countermove picker test",
)
picker_path.write_text(picker)

search_path = Path("crates/chess-search/src/lib.rs")
search = search_path.read_text()
search = replace_once(
    search,
    "const MAX_SEARCH_PLY: usize = 256;",
    "const MAX_SEARCH_PLY: usize = 256;\nconst COUNTERMOVE_SLOTS: usize = 64 * 64;",
    "countermove slots",
)
search = replace_once(
    search,
    "    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n}",
    "    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n    path_moves: [Option<ChessMove>; MAX_SEARCH_PLY],\n    countermoves: [Option<ChessMove>; COUNTERMOVE_SLOTS],\n}",
    "searcher fields",
)
search = replace_once(
    search,
    "            killers: [[None; 2]; MAX_SEARCH_PLY],\n        }",
    "            killers: [[None; 2]; MAX_SEARCH_PLY],\n            path_moves: [None; MAX_SEARCH_PLY],\n            countermoves: [None; COUNTERMOVE_SLOTS],\n        }",
    "searcher constructor",
)
search = search.replace(
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n",
    "        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.path_moves = [None; MAX_SEARCH_PLY];\n        self.countermoves = [None; COUNTERMOVE_SLOTS];\n",
)
search = search.replace(
    "MovePicker::new(&mut moves, hint, [None; 2])",
    "MovePicker::new(&mut moves, hint, [None; 2], None)",
)
loop_anchor = "        while let Some(mv) = picker.next(position) {\n            let undo = position.make_move(mv);"
search = replace_first(
    search,
    loop_anchor,
    "        while let Some(mv) = picker.next(position) {\n            self.path_moves[0] = Some(mv);\n            let undo = position.make_move(mv);",
    "root path move",
)
search = replace_once(
    search,
    "        let mut moves = moves;\n        let killers = self.killers[usize::from(ply)];\n        let mut picker = MovePicker::new(&mut moves, hint, killers);",
    "        let mut moves = moves;\n        let killers = self.killers[usize::from(ply)];\n        let previous_move = (ply > 0).then(|| self.path_moves[usize::from(ply) - 1]).flatten();\n        let countermove = previous_move\n            .and_then(|previous| self.countermoves[countermove_index(previous)]);\n        let mut picker = MovePicker::new(&mut moves, hint, killers, countermove);",
    "recursive picker countermove",
)
search = replace_once(
    search,
    loop_anchor,
    "        while let Some(mv) = picker.next(position) {\n            self.path_moves[usize::from(ply)] = Some(mv);\n            let undo = position.make_move(mv);",
    "recursive path move",
)
old_cutoff = '''                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
                    let killers = &mut self.killers[usize::from(ply)];
                    if killers[0] != Some(mv) {
                        killers[1] = killers[0];
                        killers[0] = Some(mv);
                    }
                }
                break;'''
new_cutoff = '''                if !mv.kind().is_capture() && !mv.kind().is_promotion() {
                    let killers = &mut self.killers[usize::from(ply)];
                    if killers[0] != Some(mv) {
                        killers[1] = killers[0];
                        killers[0] = Some(mv);
                    }
                    if let Some(previous) = previous_move {
                        self.countermoves[countermove_index(previous)] = Some(mv);
                    }
                }
                break;'''
search = replace_once(search, old_cutoff, new_cutoff, "countermove recording")
search = replace_once(
    search,
    "fn terminal_score(position: &Position, ply: u16) -> i32 {",
    "fn countermove_index(mv: ChessMove) -> usize {\n"
    "    usize::from(mv.from().index()) * 64 + usize::from(mv.to().index())\n"
    "}\n\n"
    "fn terminal_score(position: &Position, ply: u16) -> i32 {",
    "countermove index helper",
)
search_path.write_text(search)

q_path = Path("crates/chess-search/src/quiescence.rs")
q = q_path.read_text()
q = q.replace(
    "MovePicker::new(&mut moves, None, [None; 2])",
    "MovePicker::new(&mut moves, None, [None; 2], None)",
)
q_path.write_text(q)
