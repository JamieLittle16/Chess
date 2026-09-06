from pathlib import Path

path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

old = """        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
"""
new = """        let in_check = position.is_in_check(position.side_to_move());
        let moves = generate_legal_moves_mut(position);
        if moves.is_empty() {
            let score = terminal_score(position, ply);
"""
if old not in text:
    raise SystemExit("negamax move-generation anchor missing")
text = text.replace(old, new, 1)

old = """        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint);
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
            first_move = false;
"""
new = """        let mut moves = moves;
        let mut picker = MovePicker::new(&mut moves, hint);
        let mut move_index = 0_usize;
        while let Some(mv) = picker.next(position) {
            let first_move = move_index == 0;
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let undo = position.make_move(mv);
            let gives_check = position.is_in_check(position.side_to_move());
            let reduce = !first_move && depth >= 3 && move_index >= 3 && quiet && !in_check && !gives_check;

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
                // PVS probes later moves with a null window. LMR v1 reduces only sufficiently late
                // quiet, non-checking moves by one ply; any reduced alpha improvement is verified
                // again at full depth before it may affect the node.
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
            move_index += 1;
"""
if old not in text:
    raise SystemExit("negamax PVS loop anchor missing")
text = text.replace(old, new, 1)

path.write_text(text)
