#!/usr/bin/env python3
"""Apply draw-safe null-move substrate plus an adaptive v2 strength policy."""
from pathlib import Path
import runpy


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


# Reuse the exact v1 safety substrate: reversible null state, synthetic draw/TT isolation,
# no nested nulls and no synthetic killer pollution.
runpy.run_path("tools/apply_null_move_v1.py", run_name="__main__")
runpy.run_path("tools/fix_null_move_v1_qsearch_test_wrapper.py", run_name="__main__")

path = Path("crates/chess-search/src/lib.rs")
text = path.read_text()

text = replace_once(
    text,
    '''    const NULL_SUBTREE: Self = Self {
        synthetic: true,
        allow_null: false,
    };
}''',
    '''    const NULL_SUBTREE: Self = Self {
        synthetic: true,
        allow_null: false,
    };
    const NO_NULL: Self = Self {
        synthetic: false,
        allow_null: false,
    };
}''',
    "verification search mode",
)

text = replace_once(
    text,
    '''        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        if mode.allow_null''',
    '''        let in_check = position.is_in_check(position.side_to_move());
        let null_window = beta == alpha + 1;
        let static_eval = if mode.allow_null && !mode.synthetic && !in_check {
            Some(evaluate(position))
        } else {
            None
        };
        if mode.allow_null''',
    "single static-eval null gate",
)

text = replace_once(
    text,
    '''            && beta.abs() < MATE_TT_THRESHOLD
            && evaluate(position) >= beta
            && has_null_move_material(position)
        {
            // R=2 and the implicit passed turn consume three nominal plies. The entire child tree is
            // synthetic: no history draws, TT reads/writes, nested nulls, or killer recording.
            let undo = position.make_null_move();''',
    '''            && beta.abs() < MATE_TT_THRESHOLD
            && static_eval.is_some_and(|score| score >= beta)
            && has_null_move_material(position)
        {
            let static_eval = static_eval.expect("null gate computed static evaluation");
            let static_margin = static_eval.saturating_sub(beta);
            // V2 becomes more aggressive only when the node is deep enough and/or the static
            // position is comfortably above beta. R is the number of additional plies reduced;
            // the synthetic passed turn consumes one more nominal ply.
            let reduction: u8 = if depth >= 7 || (depth >= 6 && static_margin >= 180) {
                3
            } else {
                2
            };
            let undo = position.make_null_move();''',
    "adaptive null reduction",
)

text = replace_once(
    text,
    '''                depth - 3,
                -beta,''',
    '''                depth - reduction - 1,
                -beta,''',
    "adaptive null depth",
)

text = replace_once(
    text,
    '''            let null_score = -null_child?;
            if null_score >= beta {
                return Some(null_score);
            }
        }''',
    '''            let null_score = -null_child?;
            if null_score >= beta {
                // Deep R=3 fail-highs close to the static threshold get a real-position
                // verification search with null move disabled. This is deliberately selective:
                // strong-margin cutoffs retain the speed benefit, while the more zugzwang-prone
                // marginal cases pay for verification.
                let needs_verification = reduction >= 3 && depth >= 8 && static_margin < 160;
                if !needs_verification {
                    return Some(null_score);
                }
                let verification = self.negamax_mode(
                    position,
                    prior_history,
                    depth - reduction,
                    beta - 1,
                    beta,
                    ply,
                    path_len,
                    control,
                    SearchMode::NO_NULL,
                )?;
                if verification >= beta {
                    return Some(verification);
                }
            }
        }''',
    "deep null verification",
)

path.write_text(text)
