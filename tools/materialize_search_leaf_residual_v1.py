#!/usr/bin/env python3
"""Materialize a retained search-leaf linear residual into the Rust evaluator."""
from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

FEATURE_COUNT = 24_576
EXPECTED_FEATURE_SET = "king-piece-v1-antisymmetric-rust-classical-residual"


def rust_array(weights: list[int]) -> str:
    lines: list[str] = []
    for start in range(0, len(weights), 16):
        values = ", ".join(str(value) for value in weights[start : start + 16])
        lines.append(f"    {values},")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--expected-weights-sha256", required=True)
    parser.add_argument("--denominator", type=int, default=1)
    parser.add_argument(
        "--clamp-cp",
        type=int,
        default=0,
        help="absolute residual clamp before scaling; 0 disables clamping",
    )
    parser.add_argument("--identity-out", type=Path, required=True)
    args = parser.parse_args()

    if args.denominator <= 0:
        raise ValueError("denominator must be positive")
    if args.clamp_cp < 0:
        raise ValueError("clamp-cp must be non-negative")

    model_path = args.model_dir / "model.json"
    weights_path = args.model_dir / "weights.i16"
    report_path = args.model_dir / "report.json"
    model = json.loads(model_path.read_text())
    report = json.loads(report_path.read_text())

    if int(model["feature_count"]) != FEATURE_COUNT:
        raise ValueError("feature-count mismatch")
    if report.get("feature_set_id") != EXPECTED_FEATURE_SET:
        raise ValueError("feature-set mismatch")

    raw = weights_path.read_bytes()
    expected_bytes = FEATURE_COUNT * 2
    if len(raw) != expected_bytes:
        raise ValueError(f"expected {expected_bytes} weight bytes, got {len(raw)}")
    weights_sha = hashlib.sha256(raw).hexdigest()
    if weights_sha != args.expected_weights_sha256:
        raise ValueError(
            f"weights SHA mismatch: expected {args.expected_weights_sha256}, got {weights_sha}"
        )
    weights = list(struct.unpack(f"<{FEATURE_COUNT}h", raw))
    bias = int(model["bias_cp"])

    if args.clamp_cp:
        clamp_decl = f"const CLAMP_CP: i32 = {args.clamp_cp};\n"
        score_expr = "score.clamp(-CLAMP_CP, CLAMP_CP)"
    else:
        clamp_decl = ""
        score_expr = "score"

    module = f'''//! Generated experiment-only search-leaf linear residual.
//! Do not hand-edit: `tools/materialize_search_leaf_residual_v1.py` owns this file.

use chess_core::Position;

use crate::nnue::{{FEATURE_COUNT, active_features}};

const BIAS_CP: i32 = {bias};
const DENOMINATOR: i32 = {args.denominator};
{clamp_decl}static WEIGHTS: [i16; FEATURE_COUNT] = [
{rust_array(weights)}
];

pub(crate) fn correction(position: &Position) -> i32 {{
    let us = position.side_to_move();
    let them = us.opposite();
    let Some(us_features) = active_features(position, us) else {{
        return 0;
    }};
    let Some(them_features) = active_features(position, them) else {{
        return 0;
    }};

    let mut score = BIAS_CP;
    for feature in us_features.as_slice() {{
        score += i32::from(WEIGHTS[usize::from(feature.raw())]);
    }}
    for feature in them_features.as_slice() {{
        score -= i32::from(WEIGHTS[usize::from(feature.raw())]);
    }}
    {score_expr} / DENOMINATOR
}}
'''

    repo = args.repo.resolve()
    generated = repo / "crates/chess-eval/src/linear_residual_generated.rs"
    generated.write_text(module)

    lib_path = repo / "crates/chess-eval/src/lib.rs"
    text = lib_path.read_text()
    module_anchor = "pub mod nnue;\n"
    module_decl = "mod linear_residual_generated;\n"
    if text.count(module_anchor) != 1:
        raise ValueError("could not locate unique nnue module anchor")
    if module_decl not in text:
        text = text.replace(module_anchor, module_anchor + module_decl, 1)

    old = """    match position.side_to_move() {\n        Color::White => white_minus_black,\n        Color::Black => -white_minus_black,\n    }\n"""
    new = """    let classical = match position.side_to_move() {\n        Color::White => white_minus_black,\n        Color::Black => -white_minus_black,\n    };\n    classical + linear_residual_generated::correction(position)\n"""
    if text.count(old) != 1:
        raise ValueError("could not locate unique classical evaluator return block")
    lib_path.write_text(text.replace(old, new, 1))

    identity = {
        "schema_version": 1,
        "feature_set_id": EXPECTED_FEATURE_SET,
        "weights_sha256": weights_sha,
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
        "bias_cp": bias,
        "denominator": args.denominator,
        "clamp_cp": args.clamp_cp,
        "generated_rust_sha256": hashlib.sha256(module.encode()).hexdigest(),
    }
    args.identity_out.parent.mkdir(parents=True, exist_ok=True)
    args.identity_out.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    print(json.dumps(identity, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
