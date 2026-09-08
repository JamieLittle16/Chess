#!/usr/bin/env python3
"""Integrate the V15 two-ply same-side continuation channel into V14 search."""
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
    "self.history.score(position.side_to_move(), None, context)",
    "self.history.score(position.side_to_move(), None, None, context)",
    "root history score",
)

text = replace_once(
    text,
    """        let previous_context = if ply == 0 {
            None
        } else {
            self.move_contexts[usize::from(ply - 1)]
        };
""",
    """        let previous_context = if ply == 0 {
            None
        } else {
            self.move_contexts[usize::from(ply - 1)]
        };
        let previous_plan_context = if ply < 2 {
            None
        } else {
            self.move_contexts[usize::from(ply - 2)]
        };
""",
    "two-ply context lookup",
)

text = replace_once(
    text,
    """            self.history
                .score(position.side_to_move(), previous_context, context)
""",
    """            self.history.score(
                position.side_to_move(),
                previous_context,
                previous_plan_context,
                context,
            )
""",
    "move-picker two-ply history score",
)

text = replace_once(
    text,
    "self.history.score(side, previous_context, context),",
    "self.history.score(side, previous_context, previous_plan_context, context),",
    "LMR two-ply history score",
)

text = replace_once(
    text,
    "self.history.update(side, previous_context, context, update);",
    "self.history.update(side, previous_context, previous_plan_context, context, update);",
    "two-ply history update",
)

path.write_text(text)
print("applied V15 two-ply continuation history integration")
