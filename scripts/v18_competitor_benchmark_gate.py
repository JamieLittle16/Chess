#!/usr/bin/env python3
"""Aggregate per-engine Chessathon move-benchmark summaries and enforce the top-engine gate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DEFAULT_TARGETS = (
    "Ryan Vincent",
    "Lightning Tree",
    "Emile Andrieu",
    "what even is en passant",
    "Gijs Smit",
    "Opus Carlsen",
    "Stonkfish",
    "BetaGo",
)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("summaries", nargs="+", type=Path)
    ap.add_argument("--target", action="append", dest="targets")
    ap.add_argument("--min-mean-cp-gain", type=float, default=0.5)
    ap.add_argument("--min-pairwise-score", type=float, default=0.500001)
    ap.add_argument("--output", type=Path)
    return ap.parse_args()


def load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1:
        raise ValueError(f"unsupported benchmark summary schema in {path}")
    return payload


def main() -> int:
    args = parse_args()
    expected = tuple(args.targets or DEFAULT_TARGETS)
    by_target: dict[str, dict[str, Any]] = {}
    source_by_target: dict[str, str] = {}
    for path in args.summaries:
        payload = load(path)
        target = str(payload["target"])
        if target in by_target:
            raise SystemExit(f"duplicate summary for {target!r}: {source_by_target[target]} and {path}")
        by_target[target] = payload
        source_by_target[target] = str(path)

    missing = [target for target in expected if target not in by_target]
    unexpected = sorted(target for target in by_target if target not in expected)

    per_target: dict[str, Any] = {}
    strict_pass = not missing and not unexpected
    regression_pass = not missing and not unexpected
    total_positions = 0
    weighted_candidate_loss = 0.0
    weighted_historical_loss = 0.0
    weighted_pair_points = 0.0

    for target in expected:
        summary = by_target.get(target)
        if summary is None:
            continue
        positions = int(summary["positions"])
        candidate = summary["candidate"]
        historical = summary["historical"]
        pairwise = summary["pairwise"]
        mean_gain = float(historical["mean_cp_loss"]) - float(candidate["mean_cp_loss"])
        pair_score = float(pairwise["score"])
        strict_checks = {
            "per_position_gate_pass": bool(summary.get("gate_pass")),
            "strict_mean_cp_gain": mean_gain >= args.min_mean_cp_gain,
            "strict_pairwise_majority": pair_score >= args.min_pairwise_score,
            "best_move_match_rate_not_worse": (
                float(candidate["best_move_match_rate"]) >= float(historical["best_move_match_rate"])
            ),
            "mistakes_ge_80_not_more_frequent": (
                int(candidate["mistakes_cp_ge_80"]) <= int(historical["mistakes_cp_ge_80"])
            ),
        }
        target_regression = bool(summary.get("gate_pass"))
        target_strict = all(strict_checks.values())
        regression_pass = regression_pass and target_regression
        strict_pass = strict_pass and target_strict
        total_positions += positions
        weighted_candidate_loss += positions * float(candidate["mean_cp_loss"])
        weighted_historical_loss += positions * float(historical["mean_cp_loss"])
        weighted_pair_points += positions * pair_score
        per_target[target] = {
            "positions": positions,
            "candidate_mean_cp_loss": candidate["mean_cp_loss"],
            "historical_mean_cp_loss": historical["mean_cp_loss"],
            "mean_cp_gain": round(mean_gain, 3),
            "pairwise_score": pair_score,
            "candidate_best_move_match_rate": candidate["best_move_match_rate"],
            "historical_best_move_match_rate": historical["best_move_match_rate"],
            "regression_pass": target_regression,
            "outperformance_pass": target_strict,
            "checks": strict_checks,
            "summary_path": source_by_target[target],
        }

    aggregate_candidate = weighted_candidate_loss / total_positions if total_positions else float("nan")
    aggregate_historical = weighted_historical_loss / total_positions if total_positions else float("nan")
    aggregate_pair = weighted_pair_points / total_positions if total_positions else float("nan")
    result = {
        "schema_version": 1,
        "expected_targets": list(expected),
        "missing_targets": missing,
        "unexpected_targets": unexpected,
        "positions": total_positions,
        "aggregate": {
            "candidate_mean_cp_loss": round(aggregate_candidate, 3),
            "historical_mean_cp_loss": round(aggregate_historical, 3),
            "mean_cp_gain": round(aggregate_historical - aggregate_candidate, 3),
            "pairwise_score": round(aggregate_pair, 6),
        },
        "thresholds": {
            "minimum_per_engine_mean_cp_gain": args.min_mean_cp_gain,
            "minimum_per_engine_pairwise_score": args.min_pairwise_score,
        },
        "regression_gate_pass": regression_pass,
        "outperformance_gate_pass": strict_pass,
        "per_target": per_target,
    }
    encoded = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0 if strict_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
