#!/usr/bin/env python3
"""Run a reproducible paired Fastchess SPRT using the existing match-harness primitives.

The finite M3 harness remains the stable qualification boundary. This wrapper adds one thing only:
a predeclared pentanomial SPRT that may stop before its maximum game budget. All engine, opening,
hashing, environment and output provenance continues to come from ``match_harness``.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import match_harness as base


@dataclass(frozen=True)
class SprtBounds:
    elo0: float
    elo1: float
    alpha: float
    beta: float
    model: str

    @classmethod
    def from_json(cls, raw: object) -> "SprtBounds":
        if not isinstance(raw, dict):
            raise base.HarnessError("sprt must be an object")
        expected = set(cls.__dataclass_fields__)
        actual = set(raw)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if extra:
                details.append(f"unknown keys: {', '.join(extra)}")
            raise base.HarnessError("invalid sprt schema (" + "; ".join(details) + ")")
        bounds = cls(**raw)
        bounds.validate()
        return bounds

    def validate(self) -> None:
        if not self.elo0 < self.elo1:
            raise base.HarnessError("sprt requires elo0 < elo1")
        for name, value in (("alpha", self.alpha), ("beta", self.beta)):
            if not 0.0 < value < 1.0:
                raise base.HarnessError(f"sprt {name} must lie strictly between 0 and 1")
        if self.model not in {"logistic", "normalized"}:
            raise base.HarnessError("sprt model must be 'logistic' or 'normalized'")

    def fastchess_args(self) -> list[str]:
        self.validate()
        return [
            "-sprt",
            f"elo0={self.elo0:g}",
            f"elo1={self.elo1:g}",
            f"alpha={self.alpha:g}",
            f"beta={self.beta:g}",
            f"model={self.model}",
        ]


@dataclass(frozen=True)
class SprtProtocol:
    schema_version: int
    protocol_id: str
    runner: str
    max_games: int
    time_control: str
    concurrency: int
    seed: int
    max_moves: int
    opening_format: str
    openings_required: bool
    opening_suite_id: str
    opening_sha256: str
    paired_colour_reversal: bool
    ponder: bool
    tablebases: bool
    evaluation_adjudication: bool
    sprt: SprtBounds
    notes: str

    @classmethod
    def from_json(cls, path: Path) -> "SprtProtocol":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise base.HarnessError(f"cannot read SPRT protocol {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise base.HarnessError("SPRT protocol must be an object")

        expected = set(cls.__dataclass_fields__)
        actual = set(raw)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            details = []
            if missing:
                details.append(f"missing keys: {', '.join(missing)}")
            if extra:
                details.append(f"unknown keys: {', '.join(extra)}")
            raise base.HarnessError("invalid SPRT protocol schema (" + "; ".join(details) + ")")

        values = dict(raw)
        values["sprt"] = SprtBounds.from_json(values["sprt"])
        protocol = cls(**values)
        protocol.validate()
        return protocol

    def validate(self) -> None:
        if self.schema_version != 1:
            raise base.HarnessError(f"unsupported SPRT protocol schema {self.schema_version}")
        if not self.protocol_id.strip():
            raise base.HarnessError("protocol_id must be non-empty")
        if self.runner != "fastchess":
            raise base.HarnessError("SPRT harness supports runner='fastchess' only")
        if self.max_games <= 0 or self.max_games % 2 != 0:
            raise base.HarnessError("max_games must be a positive even integer")
        self.sprt.validate()
        self.as_finite_protocol().validate()

    def as_finite_protocol(self) -> base.Protocol:
        return base.Protocol(
            schema_version=1,
            protocol_id=self.protocol_id,
            runner=self.runner,
            games=self.max_games,
            time_control=self.time_control,
            concurrency=self.concurrency,
            seed=self.seed,
            max_moves=self.max_moves,
            opening_format=self.opening_format,
            openings_required=self.openings_required,
            opening_suite_id=self.opening_suite_id,
            opening_sha256=self.opening_sha256,
            paired_colour_reversal=self.paired_colour_reversal,
            ponder=self.ponder,
            tablebases=self.tablebases,
            evaluation_adjudication=self.evaluation_adjudication,
            notes=self.notes,
        )


def build_sprt_command(
    *,
    fastchess: Path,
    protocol: SprtProtocol,
    candidate: base.EngineSpec,
    reference: base.EngineSpec,
    paths: base.MatchPaths,
    openings: Path | None,
) -> list[str]:
    protocol.validate()
    command = base.build_fastchess_command(
        fastchess=fastchess,
        protocol=protocol.as_finite_protocol(),
        candidate=candidate,
        reference=reference,
        paths=paths,
        openings=openings,
    )
    command.extend(protocol.sprt.fastchess_args())
    return command


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--fastchess", type=Path, required=True)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--candidate-name", default="candidate")
    parser.add_argument("--reference-name", default="reference")
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument("--candidate-option", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--reference-option", action="append", default=[], metavar="NAME=VALUE")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        protocol_path = args.protocol.expanduser().resolve(strict=True)
        protocol = SprtProtocol.from_json(protocol_path)
        finite = protocol.as_finite_protocol()
        fastchess = base.require_executable(args.fastchess, "Fastchess")
        candidate = base.resolved_engine(
            name=args.candidate_name,
            executable=args.candidate,
            directory=args.candidate_dir,
            options=args.candidate_option,
            label="candidate",
        )
        reference = base.resolved_engine(
            name=args.reference_name,
            executable=args.reference,
            directory=args.reference_dir,
            options=args.reference_option,
            label="reference",
        )
        if candidate.name == reference.name:
            raise base.HarnessError("candidate and reference names must differ")

        openings = base.resolve_openings(args.openings, finite)
        paths = base.make_paths(args.output_dir)
        command = build_sprt_command(
            fastchess=fastchess,
            protocol=protocol,
            candidate=candidate,
            reference=reference,
            paths=paths,
            openings=openings,
        )
        manifest = base.initial_manifest(
            protocol_path=protocol_path,
            protocol=finite,
            fastchess=fastchess,
            candidate=candidate,
            reference=reference,
            openings=openings,
            paths=paths,
            command=command,
        )
        manifest["qualification_mode"] = "sprt"
        manifest["protocol"] = asdict(protocol)
        manifest["maximum_games"] = protocol.max_games

        if args.dry_run:
            manifest["status"] = "dry-run"
            base.write_manifest(paths.manifest, manifest)
            print(shlex.join(command))
            print(f"manifest: {paths.manifest}")
            return 0

        manifest["status"] = "running"
        manifest["started_utc"] = datetime.now(timezone.utc).isoformat()
        base.write_manifest(paths.manifest, manifest)
        started = time.monotonic()
        try:
            returncode, elapsed = base.run_and_tee(command, paths.raw_output)
        except KeyboardInterrupt:
            manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
            manifest["elapsed_seconds"] = time.monotonic() - started
            manifest["status"] = "interrupted"
            manifest["artifacts"] = base.output_artifacts(paths)
            base.write_manifest(paths.manifest, manifest)
            raise

        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["elapsed_seconds"] = elapsed
        manifest["runner_exit_code"] = returncode
        manifest["status"] = "completed" if returncode == 0 else "failed"
        manifest["artifacts"] = base.output_artifacts(paths)
        base.write_manifest(paths.manifest, manifest)
        if returncode != 0:
            print(f"Fastchess failed with exit code {returncode}", file=sys.stderr)
        return returncode
    except base.HarnessError as exc:
        print(f"SPRT harness: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("SPRT harness: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
