#!/usr/bin/env python3
"""Apply the previously screened conservative one-ply LMR policy over accepted E4 main."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_nth(text: str, old: str, new: str, occurrence: int, label: str) -> str:
    start = 0
    index = -1
    for _ in range(occurrence):
        index = text.find(old, start)
        if index < 0:
            raise SystemExit(f"{label}: occurrence {occurrence} not found")
        start = index + len(old)
    return text[:index] + new + text[index + len(old):]


path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()
text = replace_once(
    text,
    "        let moves = generate_legal_moves_mut(position);\n        if moves.is_empty() {\n            let score = terminal_score(position, ply);",
    "        let in_check = position.is_in_check(position.side_to_move());\n        let moves = generate_legal_moves_mut(position);\n        if moves.is_empty() {\n            let score = terminal_score(position, ply);",
    "recursive in-check gate",
)
old_loop = '''        let mut moves = moves;
        let killers = self.killers[usize::from(ply)];
        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {'''
new_loop = '''        let mut moves = moves;
        let killers = self.killers[usize::from(ply)];
        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut move_index = 0_usize;
        while let Some(mv) = picker.next(position) {
            let first_move = move_index == 0;
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            let reduce =
                !first_move && depth >= 3 && move_index >= 3 && quiet && !in_check && !gives_check;
            let child = if first_move {'''
text = replace_once(text, old_loop, new_loop, "recursive LMR loop")
old_probe = '''                // Principal variation search probes later moves with a one-point
                // window and verifies only genuine alpha improvements.
                let probe = self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                );
                match probe {'''
new_probe = '''                // Conservative LMR: only late quiet, non-checking moves receive one ply of
                // reduction. Any reduced alpha improvement is verified at full depth before it can
                // affect the node.
                let probe_depth = if reduce { depth - 2 } else { depth - 1 };
                let mut probe = self.negamax(
                    position,
                    prior_history,
                    probe_depth,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                );
                if reduce
                    && let Some(reduced_child) = probe
                    && -reduced_child > alpha
                {
                    probe = self.negamax(
                        position,
                        prior_history,
                        depth - 1,
                        -alpha - 1,
                        -alpha,
                        ply + 1,
                        path_len + 1,
                        control,
                    );
                }
                match probe {'''
text = replace_once(text, old_probe, new_probe, "LMR PVS probe")
text = replace_nth(
    text,
    "            first_move = false;\n",
    "            move_index += 1;\n",
    2,
    "recursive move counter",
)
path.write_text(text)
