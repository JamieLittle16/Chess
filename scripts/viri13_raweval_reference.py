#!/usr/bin/env python3
"""Query Viridithas v13 `raweval` without relying on EOF-sensitive piped UCI input.

Viridithas v13 uses a background stdin-reader thread. Feeding a complete command script and closing
stdin can make that reader terminate after the first queued command, so an ordinary `printf | engine`
is not a reliable oracle driver. This helper performs the UCI handshake interactively and waits for
acknowledgements before requesting one raw NNUE evaluation.
"""

from __future__ import annotations

import argparse
import re
import select
import subprocess
import sys
import time
from pathlib import Path

INTEGER = re.compile(r"^-?[0-9]+$")


class OracleError(RuntimeError):
    pass


def read_line(process: subprocess.Popen[str], deadline: float, transcript: list[str]) -> str:
    assert process.stdout is not None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OracleError("timed out waiting for Viridithas output")
    readable, _, _ = select.select([process.stdout], [], [], remaining)
    if not readable:
        raise OracleError("timed out waiting for Viridithas output")
    line = process.stdout.readline()
    if line == "":
        raise OracleError(f"Viridithas closed stdout early with status {process.poll()}")
    clean = line.rstrip("\r\n")
    transcript.append(clean)
    return clean


def wait_for(
    process: subprocess.Popen[str],
    expected: str,
    deadline: float,
    transcript: list[str],
) -> None:
    while read_line(process, deadline, transcript) != expected:
        pass


def send(process: subprocess.Popen[str], command: str) -> None:
    assert process.stdin is not None
    process.stdin.write(command + "\n")
    process.stdin.flush()


def raw_eval(executable: Path, fen: str, timeout: float) -> tuple[int, list[str]]:
    process = subprocess.Popen(
        [str(executable)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    transcript: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        send(process, "uci")
        wait_for(process, "uciok", deadline, transcript)
        send(process, "isready")
        wait_for(process, "readyok", deadline, transcript)
        send(process, f"position fen {fen}")
        send(process, "raweval")
        while True:
            line = read_line(process, deadline, transcript)
            if INTEGER.fullmatch(line):
                score = int(line)
                break
        send(process, "quit")
        process.stdin.close()
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if process.returncode != 0:
            raise OracleError(f"Viridithas exited with status {process.returncode}")
        return score, transcript
    except Exception:
        process.kill()
        process.wait()
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--fen", required=True)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--transcript", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        executable = args.engine.expanduser().resolve(strict=True)
        score, transcript = raw_eval(executable, args.fen, args.timeout)
        if args.transcript is not None:
            args.transcript.parent.mkdir(parents=True, exist_ok=True)
            with args.transcript.open("a", encoding="utf-8") as output:
                output.write(f"FEN: {args.fen}\n")
                for line in transcript:
                    output.write(line + "\n")
                output.write("---\n")
        print(score)
        return 0
    except (OSError, subprocess.SubprocessError, OracleError, ValueError) as exc:
        print(f"viri13 raweval reference: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
