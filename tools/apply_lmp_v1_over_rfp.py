#!/usr/bin/env python3
"""Apply a conservative late-move pruning v1 experiment over accepted RFP v1."""
from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

# Compute the LMP node gate after accepted RFP has had its chance to fail high. LMP only acts in a
# clearly fail-low shallow context, with the same low-material/mate/check exclusions as RFP.
text = replace_once(
    text,
    '''        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;''',
    '''        let lmp_margin = 90 + 60 * i32::from(depth);
        let lmp_node = depth <= 3
            && null_window
            && !in_check
            && beta.abs() < MATE_TT_THRESHOLD
            && has_reverse_futility_material(position)
            && evaluate(position).saturating_add(lmp_margin) <= alpha;
        let lmp_quiet_limit = 4 * usize::from(depth);

        debug_assert!(path_len < MAX_SEARCH_PLY);
        self.path_keys[path_len] = repetition_key;''',
    "LMP node gate",
)

text = replace_once(
    text,
    '''        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        while let Some(mv) = picker.next(position) {
            let undo = position.make_move(mv);
            let child = if first_move {''',
    '''        let mut picker = MovePicker::new(&mut moves, hint, killers);
        let mut first_move = true;
        let mut quiets_searched = 0usize;
        while let Some(mv) = picker.next(position) {
            let quiet = !mv.kind().is_capture() && !mv.kind().is_promotion();
            let protected_killer = killers.contains(&Some(mv));
            let undo = position.make_move(mv);

            // Preserve tactical moves, promotions, both killer slots and every checking quiet.
            // Only late ordinary quiets are skipped, and only after several quiet alternatives have
            // already received full search at a shallow fail-low node.
            if lmp_node
                && quiet
                && !protected_killer
                && quiets_searched >= lmp_quiet_limit
                && !position.is_in_check(position.side_to_move())
            {
                position.unmake_move(mv, undo);
                continue;
            }

            let child = if first_move {''',
    "LMP quiet skip",
)

text = replace_once(
    text,
    '''            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;

            if score > best {''',
    '''            position.unmake_move(mv, undo);
            let score = -child?;
            first_move = false;
            if quiet {
                quiets_searched = quiets_searched.saturating_add(1);
            }

            if score > best {''',
    "LMP searched-quiet count",
)

path.write_text(text)
