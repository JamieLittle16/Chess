#!/usr/bin/env python3
"""Generate deterministic Stockfish static-evaluation teacher records."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

import chess

FINAL_RE = re.compile(r"Final evaluation\s+([+-]?\d+(?:\.\d+)?)\s+\(white side\)")


def split_for(group: str, salt: str, validation: int, holdout: int) -> str:
    digest = hashlib.sha256((salt + "\0" + group).encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 1000
    if bucket < holdout:
        return "holdout"
    if bucket < holdout + validation:
        return "validation"
    return "train"


def canonical_group(board: chess.Board) -> str:
    return "position:" + " ".join(board.fen(en_passant="fen").split()[:4])


def wait_for(proc: subprocess.Popen[str], token: str) -> None:
    assert proc.stdout is not None
    for line in proc.stdout:
        if token in line:
            return
    raise RuntimeError(f"Stockfish exited before {token!r}")


def static_eval_white(proc: subprocess.Popen[str], fen: str) -> float | None:
    assert proc.stdin is not None and proc.stdout is not None
    proc.stdin.write(f"position fen {fen}\n")
    proc.stdin.write("eval\n")
    proc.stdin.flush()
    for line in proc.stdout:
        if "Final evaluation" not in line:
            continue
        if "none (in check)" in line:
            return None
        match = FINAL_RE.search(line)
        if match is None:
            raise RuntimeError(f"unrecognized Stockfish eval line: {line!r}")
        return float(match.group(1))
    raise RuntimeError("Stockfish exited during eval")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--epd", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-salt", required=True)
    parser.add_argument("--validation-permille", type=int, default=100)
    parser.add_argument("--holdout-permille", type=int, default=100)
    args = parser.parse_args()

    proc = subprocess.Popen(
        [str(args.stockfish)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    assert proc.stdin is not None
    proc.stdin.write("uci\n")
    proc.stdin.flush()
    wait_for(proc, "uciok")
    proc.stdin.write("isready\n")
    proc.stdin.flush()
    wait_for(proc, "readyok")

    written = 0
    skipped_check = 0
    source_counts: dict[str, int] = {}
    split_counts = {"train": 0, "validation": 0, "holdout": 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as out:
        for path in args.epd:
            count = 0
            with path.open(encoding="utf-8", errors="strict") as handle:
                for line_no, line in enumerate(handle, 1):
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    fields = stripped.split()
                    if len(fields) < 4:
                        raise ValueError(f"{path}:{line_no}: malformed EPD")
                    board = chess.Board(" ".join(fields[:4]) + " 0 1")
                    if board.is_check():
                        skipped_check += 1
                        continue
                    white_pawns = static_eval_white(proc, board.fen())
                    if white_pawns is None:
                        skipped_check += 1
                        continue
                    teacher_cp_white = int(round(white_pawns * 100.0))
                    teacher_cp = teacher_cp_white if board.turn == chess.WHITE else -teacher_cp_white
                    group = canonical_group(board)
                    split = split_for(
                        group,
                        args.split_salt,
                        args.validation_permille,
                        args.holdout_permille,
                    )
                    record = {
                        "schema_version": 1,
                        "group": group,
                        "source_position": f"{path.name}:line:{line_no}",
                        "split": split,
                        "fen": board.fen(),
                        "side_to_move": "white" if board.turn else "black",
                        "teacher_cp": teacher_cp,
                        "teacher_kind": "stockfish19-static-eval",
                    }
                    out.write(json.dumps(record, sort_keys=True) + "\n")
                    written += 1
                    count += 1
                    split_counts[split] += 1
            source_counts[path.name] = count

    proc.stdin.write("quit\n")
    proc.stdin.flush()
    proc.wait(timeout=10)
    manifest = {
        "schema_version": 1,
        "teacher": "Stockfish 19 static eval",
        "records": written,
        "skipped_in_check": skipped_check,
        "source_counts": source_counts,
        "split_counts": split_counts,
        "split_salt": args.split_salt,
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
