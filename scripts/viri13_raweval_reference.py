#!/usr/bin/env python3
"""Query Viridithas v13 `raweval` without relying on EOF-sensitive piped UCI input.

Viridithas v13 uses a background stdin-reader thread. Feeding a complete command script and closing
stdin can make that reader terminate after the first queued command, so an ordinary `printf | engine`
is not a reliable oracle driver. This helper performs the UCI handshake interactively and consumes
stdout through a dedicated reader thread so Python stream buffering cannot hide acknowledgements.
"""

from __future__ import annotations

import argparse
import queue
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

INTEGER = re.compile(r"^-?[0-9]+$")
EOF = object()


class OracleError(RuntimeError):
    pass


def stdout_reader(stream, lines: queue.Queue[object]) -> None:
    try:
        for line in stream:
            lines.put(line.rstrip("\r\n"))
    finally:
        lines.put(EOF)


def read_line(
    process: subprocess.Popen[str],
    lines: queue.Queue[object],
    deadline: float,
    transcript: list[str],
) -> str:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OracleError("timed out waiting for Viridithas output")
    try:
        item = lines.get(timeout=remaining)
    except queue.Empty as exc:
        raise OracleError("timed out waiting for Viridithas output") from exc
    if item is EOF:
        raise OracleError(f"Viridithas closed stdout early with status {process.poll()}")
    assert isinstance(item, str)
    transcript.append(item)
    return item


def wait_for(
    process: subprocess.Popen[str],
    lines: queue.Queue[object],
    expected: str,
    deadline: float,
    transcript: list[str],
) -> None:
    while read_line(process, lines, deadline, transcript) != expected:
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
    assert process.stdout is not None
    lines: queue.Queue[object] = queue.Queue()
    reader = threading.Thread(target=stdout_reader, args=(process.stdout, lines), daemon=True)
    reader.start()
    transcript: list[str] = []
    deadline = time.monotonic() + timeout
    try:
        send(process, "uci")
        wait_for(process, lines, "uciok", deadline, transcript)
        send(process, "isready")
        wait_for(process, lines, "readyok", deadline, transcript)
        send(process, f"position fen {fen}")
        send(process, "raweval")
        while True:
            line = read_line(process, lines, deadline, transcript)
            if INTEGER.fullmatch(line):
                score = int(line)
                break
        send(process, "quit")
        assert process.stdin is not None
        process.stdin.close()
        process.wait(timeout=max(0.1, deadline - time.monotonic()))
        if process.returncode != 0:
            raise OracleError(f"Viridithas exited with status {process.returncode}")
        reader.join(timeout=0.5)
        return score, transcript
    except Exception:
        process.kill()
        process.wait()
        reader.join(timeout=0.5)
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
