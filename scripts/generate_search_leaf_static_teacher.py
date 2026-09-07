#!/usr/bin/env python3
"""Label a certified grouped search-leaf corpus with Stockfish static evaluation."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path

import chess

FINAL_RE = re.compile(r"Final evaluation\s+([+-]?\d+(?:\.\d+)?)\s+\(white side\)")


def deterministic_split(group: str, salt: str, validation: int, holdout: int) -> str:
    if validation < 0 or holdout < 0 or validation + holdout >= 1000:
        raise ValueError("validation + holdout permille must be in [0, 999]")
    digest = hashlib.sha256((salt + "\0" + group).encode()).digest()
    bucket = int.from_bytes(digest[:8], "big") % 1000
    if bucket < holdout:
        return "holdout"
    if bucket < holdout + validation:
        return "validation"
    return "train"


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
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--split-salt", required=True)
    parser.add_argument("--validation-permille", type=int, default=100)
    parser.add_argument("--holdout-permille", type=int, default=100)
    args = parser.parse_args()

    rows: list[tuple[str, str]] = []
    seen_fens: set[str] = set()
    groups: set[str] = set()
    with args.corpus.open(encoding="utf-8", errors="strict") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                group, fen = line.split("\t", 1)
            except ValueError as error:
                raise ValueError(f"{args.corpus}:{line_no}: expected group<TAB>FEN") from error
            board = chess.Board(fen)
            canonical = board.fen(en_passant="fen")
            if canonical != fen:
                raise ValueError(f"{args.corpus}:{line_no}: non-canonical FEN")
            if fen in seen_fens:
                raise ValueError(f"{args.corpus}:{line_no}: duplicate FEN")
            seen_fens.add(fen)
            groups.add(group)
            rows.append((group, fen))
    if not rows:
        raise ValueError("search-leaf corpus is empty")

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

    args.output.parent.mkdir(parents=True, exist_ok=True)
    split_counts: Counter[str] = Counter()
    group_split: dict[str, str] = {}
    skipped_check = 0
    written = 0
    with args.output.open("w", encoding="utf-8") as out:
        for index, (group, fen) in enumerate(rows):
            board = chess.Board(fen)
            split = group_split.setdefault(
                group,
                deterministic_split(
                    group,
                    args.split_salt,
                    args.validation_permille,
                    args.holdout_permille,
                ),
            )
            if board.is_check():
                skipped_check += 1
                continue
            white_pawns = static_eval_white(proc, fen)
            if white_pawns is None:
                skipped_check += 1
                continue
            white_cp = int(round(white_pawns * 100.0))
            teacher_cp = white_cp if board.turn == chess.WHITE else -white_cp
            record = {
                "schema_version": 1,
                "group": group,
                "source_position": f"search-leaf:{index}",
                "split": split,
                "fen": fen,
                "side_to_move": "white" if board.turn == chess.WHITE else "black",
                "teacher_cp": teacher_cp,
                "teacher_kind": "stockfish19-static-eval",
            }
            out.write(json.dumps(record, sort_keys=True) + "\n")
            split_counts[split] += 1
            written += 1

    proc.stdin.write("quit\n")
    proc.stdin.flush()
    proc.wait(timeout=10)
    if proc.returncode != 0:
        stderr = proc.stderr.read() if proc.stderr is not None else ""
        raise RuntimeError(f"Stockfish exited {proc.returncode}: {stderr[-2000:]}")

    group_split_counts = Counter(group_split.values())
    if not split_counts["train"] or not split_counts["validation"] or not split_counts["holdout"]:
        raise ValueError(f"all three splits must contain positions: {dict(split_counts)}")
    manifest = {
        "schema_version": 1,
        "teacher": "Stockfish 19 static eval",
        "corpus_sha256": hashlib.sha256(args.corpus.read_bytes()).hexdigest(),
        "groups": len(groups),
        "group_split_counts": dict(sorted(group_split_counts.items())),
        "records_input": len(rows),
        "records_written": written,
        "skipped_in_check": skipped_check,
        "split_counts": dict(sorted(split_counts.items())),
        "split_salt": args.split_salt,
        "assignment_unit": "certified search-leaf root group",
        "output_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
    }
    manifest_path = args.output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
