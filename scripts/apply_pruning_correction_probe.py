#!/usr/bin/env python3
"""Materialize M6 pruning-model experiments over the accepted production search."""

from __future__ import annotations

import argparse
from pathlib import Path


class PatchError(RuntimeError):
    pass


def replace_exact(text: str, old: str, new: str, *, count: int = 1, label: str) -> str:
    actual = text.count(old)
    if actual != count:
        raise PatchError(f"{label}: expected {count} occurrence(s), found {actual}")
    return text.replace(old, new, count)


def apply_gestalt_pruning(text: str) -> str:
    return replace_exact(
        text,
        "            Some(evaluate(position))\n",
        "            Some(self.leaf_evaluate(position))\n",
        label="mature pruning evaluator",
    )


def apply_pawn_correction(text: str) -> str:
    text = replace_exact(
        text,
        "mod move_picker;\nmod quiescence;\nmod root_analysis;\n",
        "mod correction_history;\nmod move_picker;\nmod quiescence;\nmod root_analysis;\n",
        label="correction module",
    )
    text = replace_exact(
        text,
        "use move_picker::MovePicker;",
        "use correction_history::PawnCorrectionHistory;\nuse move_picker::MovePicker;",
        label="correction import",
    )
    text = replace_exact(
        text,
        """    path_keys: [u64; MAX_SEARCH_PLY],\n    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n    gestalt: Option<GestaltSearchEvaluator>,\n}""",
        """    path_keys: [u64; MAX_SEARCH_PLY],\n    killers: [[Option<ChessMove>; 2]; MAX_SEARCH_PLY],\n    pawn_correction: PawnCorrectionHistory,\n    gestalt: Option<GestaltSearchEvaluator>,\n}""",
        label="Searcher correction field",
    )
    text = replace_exact(
        text,
        """            path_keys: [0; MAX_SEARCH_PLY],\n            killers: [[None; 2]; MAX_SEARCH_PLY],\n            gestalt: GestaltSearchEvaluator::from_environment(),\n""",
        """            path_keys: [0; MAX_SEARCH_PLY],\n            killers: [[None; 2]; MAX_SEARCH_PLY],\n            pawn_correction: PawnCorrectionHistory::new(),\n            gestalt: GestaltSearchEvaluator::from_environment(),\n""",
        label="Searcher correction construction",
    )
    text = replace_exact(
        text,
        """        self.nodes = 1;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n""",
        """        self.nodes = 1;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.pawn_correction.clear();\n        self.reset_leaf_evaluator(position);\n""",
        label="fixed-depth correction reset",
    )
    text = replace_exact(
        text,
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.reset_leaf_evaluator(position);\n        let mut last_completed = None;\n""",
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.pawn_correction.clear();\n        self.reset_leaf_evaluator(position);\n        let mut last_completed = None;\n""",
        label="iterative correction reset",
    )

    old_eval = """        let pruning_static_eval = if pruning_eligible {\n            if !has_legal_move_mut(position) {\n                let score = terminal_score(position, ply);\n                self.table\n                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);\n                return Some(score);\n            }\n            Some(evaluate(position))\n        } else {\n            None\n        };\n        if let Some(static_eval) = pruning_static_eval {\n"""
    new_eval = """        let pruning_raw_eval = if pruning_eligible {\n            if !has_legal_move_mut(position) {\n                let score = terminal_score(position, ply);\n                self.table\n                    .store(key, depth, score_to_tt(score, ply), Bound::Exact, None);\n                return Some(score);\n            }\n            Some(evaluate(position))\n        } else {\n            None\n        };\n        let pruning_static_eval = pruning_raw_eval.map(|raw| {\n            raw.saturating_add(self.pawn_correction.correction(position))\n        });\n        if let Some(static_eval) = pruning_static_eval {\n"""
    text = replace_exact(text, old_eval, new_eval, label="corrected pruning static eval")

    old_bound = """        let bound = if best <= alpha_original {\n            Bound::Upper\n        } else if best >= beta {\n            Bound::Lower\n        } else {\n            Bound::Exact\n        };\n        self.table\n            .store(key, depth, score_to_tt(best, ply), bound, best_move);\n"""
    new_bound = """        let bound = if best <= alpha_original {\n            Bound::Upper\n        } else if best >= beta {\n            Bound::Lower\n        } else {\n            Bound::Exact\n        };\n        if let Some(raw_eval) = pruning_raw_eval\n            && best.abs() < MATE_TT_THRESHOLD\n        {\n            // Bound-aware learning: a lower bound only supports an upward correction, while an\n            // upper bound only supports a downward correction. Exact values support either.\n            let residual = best.saturating_sub(raw_eval);\n            let supported = match bound {\n                Bound::Exact => true,\n                Bound::Lower => residual > 0,\n                Bound::Upper => residual < 0,\n            };\n            if supported {\n                self.pawn_correction.update(position, residual, depth);\n            }\n        }\n        self.table\n            .store(key, depth, score_to_tt(best, ply), bound, best_move);\n"""
    text = replace_exact(text, old_bound, new_bound, label="correction learning")
    return text


def patch_root_analysis() -> None:
    path = Path("crates/chess-search/src/root_analysis.rs")
    text = path.read_text(encoding="utf-8")
    text = replace_exact(
        text,
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        // Root analysis must use the same derived learned-evaluation state as ordinary search.\n""",
        """        self.nodes = 0;\n        self.tt_hits = 0;\n        self.killers = [[None; 2]; MAX_SEARCH_PLY];\n        self.pawn_correction.clear();\n        // Root analysis must use the same derived learned-evaluation state as ordinary search.\n""",
        label="root-analysis correction reset",
    )
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variant", choices=("pawn-correction", "gestalt-pruning"), required=True)
    args = parser.parse_args()

    path = Path("crates/chess-search/src/lib.rs")
    text = path.read_text(encoding="utf-8")
    if args.variant == "pawn-correction":
        text = apply_pawn_correction(text)
        path.write_text(text, encoding="utf-8")
        patch_root_analysis()
    else:
        path.write_text(apply_gestalt_pruning(text), encoding="utf-8")

    print(f"applied M6 pruning-model candidate: {args.variant}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
