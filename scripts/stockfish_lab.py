#!/usr/bin/env python3
"""Shared deterministic Stockfish analysis helpers for offline strength work.

This module is intentionally outside the Rust runtime dependency graph. It depends on the pinned
`chess` package from `tools/requirements-analysis.txt` and talks to a caller-supplied UCI engine.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import chess
import chess.engine

MATE_CP = 100_000


@dataclass(frozen=True)
class ScoreRecord:
    cp: int
    mate: int | None
    expectation: float
    wins: int
    draws: int
    losses: int


@dataclass(frozen=True)
class AnalysisRecord:
    score: ScoreRecord
    best_move: str | None
    pv: tuple[str, ...]
    depth: int | None
    seldepth: int | None
    nodes: int | None
    nps: int | None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def score_record(score: chess.engine.PovScore, pov: chess.Color, ply: int) -> ScoreRecord:
    relative = score.pov(pov)
    cp = relative.score(mate_score=MATE_CP)
    if cp is None:
        raise RuntimeError("score unexpectedly lacked centipawn/mate representation")
    wdl = relative.wdl(model="sf", ply=ply)
    return ScoreRecord(
        cp=cp,
        mate=relative.mate(),
        expectation=wdl.expectation(),
        wins=wdl.wins,
        draws=wdl.draws,
        losses=wdl.losses,
    )


def analysis_record(
    board: chess.Board,
    info: chess.engine.InfoDict,
    pov: chess.Color,
) -> AnalysisRecord:
    raw_score = info.get("score")
    if raw_score is None:
        raise RuntimeError("teacher analysis returned no score")
    pv_moves = tuple(move.uci() for move in info.get("pv", []))
    return AnalysisRecord(
        score=score_record(raw_score, pov, board.ply()),
        best_move=pv_moves[0] if pv_moves else None,
        pv=pv_moves,
        depth=info.get("depth"),
        seldepth=info.get("seldepth"),
        nodes=info.get("nodes"),
        nps=info.get("nps"),
    )


class StockfishTeacher:
    """Pinned-resource Stockfish analysis session.

    The caller chooses the executable and fixed node budget. Threads/hash are explicit so a dataset
    or diagnostic run can be reproduced independently of local GUI configuration.
    """

    def __init__(
        self,
        executable: Path,
        *,
        nodes: int,
        threads: int = 1,
        hash_mb: int = 32,
    ) -> None:
        if nodes <= 0:
            raise ValueError("nodes must be positive")
        self.executable = executable.resolve()
        self.nodes = nodes
        self.threads = threads
        self.hash_mb = hash_mb
        self.engine: chess.engine.SimpleEngine | None = None

    def __enter__(self) -> "StockfishTeacher":
        self.engine = chess.engine.SimpleEngine.popen_uci(str(self.executable))
        self.engine.configure({"Threads": self.threads, "Hash": self.hash_mb})
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.engine is not None:
            self.engine.quit()
            self.engine = None

    def analyse(
        self,
        board: chess.Board,
        *,
        pov: chess.Color | None = None,
        root_move: chess.Move | None = None,
    ) -> AnalysisRecord:
        if self.engine is None:
            raise RuntimeError("teacher must be used as a context manager")
        root_moves = None if root_move is None else [root_move]
        info = self.engine.analyse(
            board,
            chess.engine.Limit(nodes=self.nodes),
            root_moves=root_moves,
            info=chess.engine.INFO_ALL,
        )
        if isinstance(info, list):
            if not info:
                raise RuntimeError("teacher returned an empty multipv result")
            info = info[0]
        return analysis_record(board, info, board.turn if pov is None else pov)

    def manifest(self) -> dict[str, Any]:
        engine_id: dict[str, Any] = {}
        if self.engine is not None:
            engine_id = dict(self.engine.id)
        return {
            "engine_path": str(self.executable),
            "engine_sha256": sha256_file(self.executable),
            "engine_id": engine_id,
            "nodes_per_analysis": self.nodes,
            "threads": self.threads,
            "hash_mb": self.hash_mb,
            "python_chess_version": importlib.metadata.version("chess"),
        }


def move_kind(board: chess.Board, move: chess.Move) -> str:
    if move.promotion:
        return "capture_promotion" if board.is_capture(move) else "promotion"
    if board.is_capture(move):
        return "capture"
    if board.gives_check(move):
        return "quiet_check"
    return "quiet"


def phase_label(board: chess.Board) -> str:
    """Use the engine's 24-point non-pawn phase convention for coarse diagnostics."""
    weights = {
        chess.KNIGHT: 1,
        chess.BISHOP: 1,
        chess.ROOK: 2,
        chess.QUEEN: 4,
    }
    phase = sum(
        len(board.pieces(piece_type, color)) * weight
        for piece_type, weight in weights.items()
        for color in (chess.WHITE, chess.BLACK)
    )
    if phase >= 18:
        return "opening_or_early_middlegame"
    if phase >= 8:
        return "middlegame"
    return "endgame"


def loss_bucket(cp_loss: int) -> str:
    if cp_loss >= 300:
        return "severe_blunder"
    if cp_loss >= 150:
        return "blunder"
    if cp_loss >= 80:
        return "mistake"
    if cp_loss >= 30:
        return "inaccuracy"
    return "small"


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def as_jsonable(record: AnalysisRecord) -> dict[str, Any]:
    payload = asdict(record)
    payload["pv"] = list(record.pv)
    return payload
