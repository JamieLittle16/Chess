#!/usr/bin/env python3
"""Blend trained linear residuals and materialize the Rust evaluation candidate."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

FEATURE_COUNT = 24_576
COEFFICIENTS = {"static": 7000, "alpha300": 1500, "diverse": 1500}
CLAMP_CP = 400
DENOMINATOR = 3


def load_model(path: Path) -> tuple[np.ndarray, dict[str, object]]:
    meta = json.loads((path / "model.json").read_text())
    weights = np.fromfile(path / "weights.i16", dtype="<i2").astype(np.int64)
    if weights.shape != (FEATURE_COUNT,):
        raise ValueError(f"{path}: expected {FEATURE_COUNT} weights, got {weights.shape}")
    if int(meta["feature_count"]) != FEATURE_COUNT:
        raise ValueError(f"{path}: feature-count mismatch")
    return weights, meta


def rust_array(weights: np.ndarray) -> str:
    lines = []
    for start in range(0, FEATURE_COUNT, 16):
        values = ", ".join(str(int(value)) for value in weights[start : start + 16])
        lines.append(f"    {values},")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--static-model", type=Path, required=True)
    parser.add_argument("--alpha300-model", type=Path, required=True)
    parser.add_argument("--diverse-model", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    parser.add_argument("--provenance", type=Path, required=True)
    args = parser.parse_args()

    roots = {
        "static": args.static_model,
        "alpha300": args.alpha300_model,
        "diverse": args.diverse_model,
    }
    models = {name: load_model(path) for name, path in roots.items()}
    weighted = sum(COEFFICIENTS[name] * models[name][0] for name in COEFFICIENTS)
    blend = np.rint(weighted / 10000.0)
    blend = np.clip(blend, -32768, 32767).astype(np.int16)
    bias = int(
        round(
            sum(
                COEFFICIENTS[name] * int(models[name][1]["bias_cp"])
                for name in COEFFICIENTS
            )
            / 10000.0
        )
    )

    module = f'''//! Generated experiment-only sparse linear residual.
//! Do not hand-edit: `tools/apply_rust_linear_residual_v1.py` materializes this file.

use chess_core::Position;

use crate::nnue::{{FEATURE_COUNT, active_features}};

const BIAS_CP: i32 = {bias};
const CLAMP_CP: i32 = {CLAMP_CP};
const DENOMINATOR: i32 = {DENOMINATOR};
static WEIGHTS: [i16; FEATURE_COUNT] = [
{rust_array(blend)}
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
    score.clamp(-CLAMP_CP, CLAMP_CP) / DENOMINATOR
}}
'''

    repo = args.repo.resolve()
    module_path = repo / "crates/chess-eval/src/linear_residual_generated.rs"
    module_path.write_text(module)
    lib_path = repo / "crates/chess-eval/src/lib.rs"
    text = lib_path.read_text()
    module_anchor = "pub mod nnue;\n"
    if text.count(module_anchor) != 1:
        raise ValueError("could not locate unique nnue module anchor")
    text = text.replace(module_anchor, module_anchor + "mod linear_residual_generated;\n", 1)
    old = """    match position.side_to_move() {\n        Color::White => white_minus_black,\n        Color::Black => -white_minus_black,\n    }\n"""
    new = """    let classical = match position.side_to_move() {\n        Color::White => white_minus_black,\n        Color::Black => -white_minus_black,\n    };\n    classical + linear_residual_generated::correction(position)\n"""
    if text.count(old) != 1:
        raise ValueError("could not locate unique classical evaluator return block")
    lib_path.write_text(text.replace(old, new, 1))

    blend_bytes = blend.astype("<i2").tobytes()
    provenance = {
        "schema_version": 1,
        "feature_set_id": "king-piece-v1-antisymmetric-rust-classical-residual",
        "coefficients_basis_points": COEFFICIENTS,
        "bias_cp_before_scale": bias,
        "clamp_cp_before_scale": CLAMP_CP,
        "final_correction_denominator": DENOMINATOR,
        "weights_sha256": hashlib.sha256(blend_bytes).hexdigest(),
        "components": {
            name: {
                "weights_sha256": hashlib.sha256((roots[name] / "weights.i16").read_bytes()).hexdigest(),
                "model": models[name][1],
            }
            for name in COEFFICIENTS
        },
    }
    args.provenance.parent.mkdir(parents=True, exist_ok=True)
    args.provenance.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    print(json.dumps(provenance, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
