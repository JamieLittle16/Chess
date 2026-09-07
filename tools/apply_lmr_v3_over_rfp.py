#!/usr/bin/env python3
"""Apply adaptive, fully-verified late-move reductions v3 over accepted RFP."""
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
    '''        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                )
            } else {
                // Principal variation search probes later moves with a one-point
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
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            depth - 1,
                            -beta,
                            -alpha,
                            ply + 1,
                            path_len + 1,
                            control,
                        ),
                    probe => probe,
                }
            };
            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;''',
    '''        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        let mut move_index = 0usize;
        while let Some(mv) = picker.next(position) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            let child = if first_move {
                self.negamax(
                    position,
                    prior_history,
                    depth - 1,
                    -beta,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                )
            } else {
                // Adaptive LMR v3. Only late ordinary quiets in non-check nodes are reduced. The
                // schedule becomes more aggressive only at deeper nodes and much later moves.
                // Any reduced alpha raise is re-probed at full depth before normal PVS verification,
                // so a reduced result can never directly become a principal score or beta cutoff.
                let reduction = if !in_check && quiet && !protected_killer && !gives_check {
                    lmr_v3_reduction(depth, move_index)
                } else {
                    0
                };
                let full_depth = depth - 1;
                let reduced_depth = full_depth.saturating_sub(reduction);
                let reduced_probe = self.negamax(
                    position,
                    prior_history,
                    reduced_depth,
                    -alpha - 1,
                    -alpha,
                    ply + 1,
                    path_len + 1,
                    control,
                );
                let probe = match reduced_probe {
                    Some(reduced_child) if reduction > 0 && -reduced_child > alpha => self.negamax(
                        position,
                        prior_history,
                        full_depth,
                        -alpha - 1,
                        -alpha,
                        ply + 1,
                        path_len + 1,
                        control,
                    ),
                    reduced_probe => reduced_probe,
                };
                match probe {
                    Some(probe_child) if -probe_child > alpha && -probe_child < beta => self
                        .negamax(
                            position,
                            prior_history,
                            full_depth,
                            -beta,
                            -alpha,
                            ply + 1,
                            path_len + 1,
                            control,
                        ),
                    probe => probe,
                }
            };
            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;
            move_index = move_index.saturating_add(1);''',
    "adaptive LMR move loop",
)

text = replace_once(
    text,
    "fn has_reverse_futility_material(position: &Position) -> bool {",
    '''fn lmr_v3_reduction(depth: u8, move_index: usize) -> u8 {
    if depth >= 9 && move_index >= 12 {
        3
    } else if depth >= 6 && move_index >= 8 {
        2
    } else if depth >= 3 && move_index >= 4 {
        1
    } else {
        0
    }
}

fn has_reverse_futility_material(position: &Position) -> bool {''',
    "LMR reduction schedule",
)

path.write_text(text)
