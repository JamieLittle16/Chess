#!/usr/bin/env python3
"""Apply the previously tested conservative LMR policy over the stronger E2 evaluator."""
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
    "        let moves = generate_legal_moves_mut(position);\n        if moves.is_empty() {\n            let score = terminal_score(position, ply);",
    "        let in_check = position.is_in_check(position.side_to_move());\n        let moves = generate_legal_moves_mut(position);\n        if moves.is_empty() {\n            let score = terminal_score(position, ply);",
    "in-check gate",
)

text = replace_once(
    text,
    "        let mut picker = MovePicker::new(&mut moves, hint);\n        let mut first_move = true;\n        while let Some(mv) = picker.next(position) {\n            let undo = position.make_move(mv);\n            let child = if first_move {",
    "        let mut picker = MovePicker::new(&mut moves, hint);\n        let mut move_index = 0_usize;\n        while let Some(mv) = picker.next(position) {\n            let first_move = move_index == 0;\n            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();\n            let undo = position.make_move(mv);\n            let gives_check = position.is_in_check(position.side_to_move());\n            let reduce =\n                !first_move && depth >= 3 && move_index >= 3 && quiet && !in_check && !gives_check;\n            let child = if first_move {",
    "LMR loop setup",
)

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
new_probe = '''                // Conservative LMR v2 deliberately reuses the old v1 policy on the stronger E2
                // evaluator. Only sufficiently late quiet, non-checking moves receive one ply of
                // reduction, and any reduced alpha improvement is verified at full depth before
                // it can affect the node.
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
text = replace_once(text, old_probe, new_probe, "LMR probe")
text = replace_once(
    text,
    "            first_move = false;\n\n            if score > best {",
    "            move_index += 1;\n\n            if score > best {",
    "LMR move counter",
)

path.write_text(text)
