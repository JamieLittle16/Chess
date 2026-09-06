#!/usr/bin/env python3
"""Run a reproducible paired UCI match through Fastchess.

This script owns experiment provenance, not chess adjudication. Fastchess remains the tournament
runner; this wrapper validates the repository protocol, builds one explicit command line, hashes all
important inputs, and stores a manifest plus raw runner output beside the PGN.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / "match" / "protocols" / "m3-baseline-v1.json"
MANIFEST_SCHEMA_VERSION = 1


class HarnessError(ValueError):
    """A user/configuration error that should prevent a qualification run."""


@dataclass(frozen=True)
class Protocol:
    schema_version: int
    protocol_id: str
    runner: str
    games: int
    time_control: str
    concurrency: int
    seed: int
    max_moves: int
    opening_format: str
    openings_required: bool
    paired_colour_reversal: bool
    ponder: bool
    tablebases: bool
    evaluation_adjudication: bool
    notes: str

    @classmethod
    def from_json(cls, path: Path) -> "Protocol":
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HarnessError(f"cannot read protocol {path}: {exc}") from exc

        expected = set(cls.__dataclass_fields__)
        actual = set(raw)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            detail = []
            if missing:
                detail.append(f"missing keys: {', '.join(missing)}")
            if extra:
                detail.append(f"unknown keys: {', '.join(extra)}")
            raise HarnessError("invalid protocol schema (" + "; ".join(detail) + ")")

        protocol = cls(**raw)
        protocol.validate()
        return protocol

    def validate(self) -> None:
        if self.schema_version != 1:
            raise HarnessError(f"unsupported protocol schema {self.schema_version}")
        if self.runner != "fastchess":
            raise HarnessError("M3 harness currently supports runner='fastchess' only")
        if self.games <= 0 or self.games % 2 != 0:
            raise HarnessError("protocol games must be a positive even integer")
        if self.concurrency <= 0:
            raise HarnessError("protocol concurrency must be positive")
        if self.max_moves <= 0:
            raise HarnessError("protocol max_moves must be positive")
        if not self.time_control.strip():
            raise HarnessError("protocol time_control must be non-empty")
        if self.opening_format not in {"epd", "pgn"}:
            raise HarnessError("opening_format must be 'epd' or 'pgn'")
        if not self.paired_colour_reversal:
            raise HarnessError("M3 qualification requires paired colour reversal")
        if self.ponder:
            raise HarnessError("M3 baseline requires ponder=false")
        if self.tablebases:
            raise HarnessError("M3 baseline requires tablebases=false")
        if self.evaluation_adjudication:
            raise HarnessError("M3 baseline forbids evaluation-based draw/resign adjudication")


@dataclass(frozen=True)
class FileIdentity:
    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class EngineSpec:
    name: str
    executable: Path
    directory: Path
    options: tuple[str, ...]


@dataclass(frozen=True)
class MatchPaths:
    output_dir: Path
    manifest: Path
    raw_output: Path
    pgn: Path
    engine_log: Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def identify_file(path: Path) -> FileIdentity:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise HarnessError(f"not a regular file: {resolved}")
    return FileIdentity(
        path=str(resolved),
        sha256=sha256_file(resolved),
        size_bytes=resolved.stat().st_size,
    )


def require_executable(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise HarnessError(f"{label} is not a regular file: {resolved}")
    if not os.access(resolved, os.X_OK):
        raise HarnessError(f"{label} is not executable: {resolved}")
    return resolved


def parse_engine_option(text: str) -> str:
    name, separator, value = text.partition("=")
    if not separator or not name.strip() or not value.strip():
        raise HarnessError(f"engine option must be NAME=VALUE, got {text!r}")
    if any(char.isspace() for char in name):
        raise HarnessError(f"engine option name may not contain whitespace: {name!r}")
    return f"option.{name}={value}"


def build_fastchess_command(
    *,
    fastchess: Path,
    protocol: Protocol,
    candidate: EngineSpec,
    reference: EngineSpec,
    paths: MatchPaths,
    openings: Path | None,
) -> list[str]:
    protocol.validate()
    if openings is None and protocol.openings_required:
        raise HarnessError("qualification protocol requires an opening file")

    command = [
        str(fastchess),
        "-engine",
        f"name={candidate.name}",
        f"cmd={candidate.executable}",
        f"dir={candidate.directory}",
        *candidate.options,
        "-engine",
        f"name={reference.name}",
        f"cmd={reference.executable}",
        f"dir={reference.directory}",
        *reference.options,
        "-each",
        "proto=uci",
        f"tc={protocol.time_control}",
        "-rounds",
        str(protocol.games // 2),
        "-games",
        "2",
        "-repeat",
        "-srand",
        str(protocol.seed),
        "-concurrency",
        str(protocol.concurrency),
        "-maxmoves",
        str(protocol.max_moves),
        "-report",
        "penta=true",
        "-pgnout",
        f"file={paths.pgn}",
        "append=false",
        "-log",
        f"file={paths.engine_log}",
        "level=info",
        "engine=true",
        "append=false",
    ]
    if openings is not None:
        command.extend(
            [
                "-openings",
                f"file={openings}",
                f"format={protocol.opening_format}",
                "order=random",
            ]
        )
    return command


def _run_capture(command: Sequence[str], *, timeout: float = 5.0) -> str | None:
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = completed.stdout.strip()
    return output or None


def fastchess_version(executable: Path) -> str | None:
    for flag in ("--version", "-version"):
        output = _run_capture([str(executable), flag])
        if output:
            return output
    return None


def git_metadata() -> dict[str, Any]:
    def git(*args: str) -> str | None:
        return _run_capture(["git", *args])

    status = git("status", "--porcelain")
    return {
        "head": git("rev-parse", "HEAD"),
        "branch": git("branch", "--show-current"),
        "dirty": bool(status),
        "status_porcelain": status or "",
    }


def cpu_description() -> str | None:
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.lower().startswith("model name"):
                    return line.partition(":")[2].strip()
        except OSError:
            pass
    processor = platform.processor().strip()
    return processor or None


def environment_metadata() -> dict[str, Any]:
    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu": cpu_description(),
        "logical_cpus": os.cpu_count(),
        "python": sys.version,
        "rustc": _run_capture(["rustc", "--version", "--verbose"]),
    }


def make_paths(output_dir: Path) -> MatchPaths:
    output = output_dir.expanduser().resolve()
    if output.exists():
        if not output.is_dir():
            raise HarnessError(f"output path exists and is not a directory: {output}")
        if any(output.iterdir()):
            raise HarnessError(f"output directory must be empty: {output}")
    else:
        output.mkdir(parents=True)

    return MatchPaths(
        output_dir=output,
        manifest=output / "manifest.json",
        raw_output=output / "fastchess.stdout.log",
        pgn=output / "games.pgn",
        engine_log=output / "uci.log",
    )


def write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def initial_manifest(
    *,
    protocol_path: Path,
    protocol: Protocol,
    fastchess: Path,
    candidate: EngineSpec,
    reference: EngineSpec,
    openings: Path | None,
    paths: MatchPaths,
    command: Sequence[str],
) -> dict[str, Any]:
    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "status": "prepared",
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "protocol": asdict(protocol),
        "protocol_file": asdict(identify_file(protocol_path)),
        "runner": {
            "file": asdict(identify_file(fastchess)),
            "version_output": fastchess_version(fastchess),
        },
        "candidate": {
            "name": candidate.name,
            "file": asdict(identify_file(candidate.executable)),
            "directory": str(candidate.directory),
            "options": list(candidate.options),
        },
        "reference": {
            "name": reference.name,
            "file": asdict(identify_file(reference.executable)),
            "directory": str(reference.directory),
            "options": list(reference.options),
        },
        "openings": None if openings is None else asdict(identify_file(openings)),
        "repository": git_metadata(),
        "environment": environment_metadata(),
        "command": {
            "argv": list(command),
            "shell": shlex.join(command),
        },
        "outputs": {
            "directory": str(paths.output_dir),
            "raw_runner_output": str(paths.raw_output),
            "pgn": str(paths.pgn),
            "engine_log": str(paths.engine_log),
        },
    }


def run_and_tee(command: Sequence[str], raw_output: Path) -> tuple[int, float]:
    started = time.monotonic()
    with raw_output.open("w", encoding="utf-8") as log:
        try:
            process = subprocess.Popen(
                command,
                cwd=REPO_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise HarnessError(f"failed to launch Fastchess: {exc}") from exc

        assert process.stdout is not None
        try:
            for line in process.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log.write(line)
                log.flush()
            returncode = process.wait()
        except KeyboardInterrupt:
            process.send_signal(subprocess.signal.SIGINT)
            returncode = process.wait()
            raise
        finally:
            process.stdout.close()
    return returncode, time.monotonic() - started


def resolved_engine(
    *,
    name: str,
    executable: Path,
    directory: Path | None,
    options: Iterable[str],
    label: str,
) -> EngineSpec:
    resolved_executable = require_executable(executable, label)
    resolved_directory = (
        resolved_executable.parent
        if directory is None
        else directory.expanduser().resolve(strict=True)
    )
    if not resolved_directory.is_dir():
        raise HarnessError(f"{label} directory is not a directory: {resolved_directory}")
    if not name.strip():
        raise HarnessError(f"{label} name must be non-empty")
    return EngineSpec(
        name=name.strip(),
        executable=resolved_executable,
        directory=resolved_directory,
        options=tuple(parse_engine_option(option) for option in options),
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True, help="candidate UCI executable")
    parser.add_argument("--reference", type=Path, required=True, help="reference UCI executable")
    parser.add_argument("--fastchess", type=Path, required=True, help="Fastchess executable")
    parser.add_argument("--openings", type=Path, help="opening suite required by qualification protocol")
    parser.add_argument("--output-dir", type=Path, required=True, help="new or empty results directory")
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--candidate-name", default="candidate")
    parser.add_argument("--reference-name", default="reference")
    parser.add_argument("--candidate-dir", type=Path)
    parser.add_argument("--reference-dir", type=Path)
    parser.add_argument(
        "--candidate-option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="repeatable Fastchess UCI option for candidate",
    )
    parser.add_argument(
        "--reference-option",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="repeatable Fastchess UCI option for reference",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate inputs and write manifest without launching Fastchess",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        protocol_path = args.protocol.expanduser().resolve(strict=True)
        protocol = Protocol.from_json(protocol_path)
        fastchess = require_executable(args.fastchess, "Fastchess")
        candidate = resolved_engine(
            name=args.candidate_name,
            executable=args.candidate,
            directory=args.candidate_dir,
            options=args.candidate_option,
            label="candidate",
        )
        reference = resolved_engine(
            name=args.reference_name,
            executable=args.reference,
            directory=args.reference_dir,
            options=args.reference_option,
            label="reference",
        )
        if candidate.name == reference.name:
            raise HarnessError("candidate and reference names must differ")

        openings = None
        if args.openings is not None:
            openings = args.openings.expanduser().resolve(strict=True)
            if not openings.is_file():
                raise HarnessError(f"openings is not a regular file: {openings}")

        paths = make_paths(args.output_dir)
        command = build_fastchess_command(
            fastchess=fastchess,
            protocol=protocol,
            candidate=candidate,
            reference=reference,
            paths=paths,
            openings=openings,
        )
        manifest = initial_manifest(
            protocol_path=protocol_path,
            protocol=protocol,
            fastchess=fastchess,
            candidate=candidate,
            reference=reference,
            openings=openings,
            paths=paths,
            command=command,
        )
        if args.dry_run:
            manifest["status"] = "dry-run"
            write_manifest(paths.manifest, manifest)
            print(shlex.join(command))
            print(f"manifest: {paths.manifest}")
            return 0

        manifest["status"] = "running"
        manifest["started_utc"] = datetime.now(timezone.utc).isoformat()
        write_manifest(paths.manifest, manifest)
        returncode, elapsed = run_and_tee(command, paths.raw_output)
        manifest["finished_utc"] = datetime.now(timezone.utc).isoformat()
        manifest["elapsed_seconds"] = elapsed
        manifest["runner_exit_code"] = returncode
        manifest["status"] = "completed" if returncode == 0 else "failed"
        write_manifest(paths.manifest, manifest)
        if returncode != 0:
            print(f"Fastchess failed with exit code {returncode}", file=sys.stderr)
        return returncode
    except HarnessError as exc:
        print(f"match harness: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("match harness: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
