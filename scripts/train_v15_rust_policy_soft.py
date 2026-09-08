#!/usr/bin/env python3
"""Train the cheap H64 root policy from ranked Rust V15 candidate scores.

Unlike the older top-1 pilot, this uses a soft target over the teacher's top root alternatives.  Score
weights are based on clipped centipawn gaps, so near-equal moves share probability mass while clearly
inferior alternatives are suppressed.  Runtime features exactly match the deployment path: the
expensive `gives_check` bit is forced to zero.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import chess
import numpy as np
import torch
from torch import nn

PLANES = 12
SQUARES = 64
BOARD_FEATURES = PLANES * SQUARES + 5
MOVE_FEATURES = 64 + 64 + 6 + 6 + 5 + 4


def board_features(board: chess.Board) -> np.ndarray:
    x = np.zeros(BOARD_FEATURES, dtype=np.float32)
    for sq, piece in board.piece_map().items():
        plane = (0 if piece.color == chess.WHITE else 6) + piece.piece_type - 1
        x[plane * 64 + sq] = 1.0
    off = 12 * 64
    x[off] = 1.0 if board.turn == chess.WHITE else -1.0
    x[off + 1] = float(board.has_kingside_castling_rights(chess.WHITE))
    x[off + 2] = float(board.has_queenside_castling_rights(chess.WHITE))
    x[off + 3] = float(board.has_kingside_castling_rights(chess.BLACK))
    x[off + 4] = float(board.has_queenside_castling_rights(chess.BLACK))
    return x


def move_features(board: chess.Board, move: chess.Move) -> np.ndarray:
    x = np.zeros(MOVE_FEATURES, dtype=np.float32)
    o = 0
    x[o + move.from_square] = 1.0; o += 64
    x[o + move.to_square] = 1.0; o += 64
    piece = board.piece_at(move.from_square)
    if piece is not None:
        x[o + piece.piece_type - 1] = 1.0
    o += 6
    captured = board.piece_at(move.to_square)
    if board.is_en_passant(move):
        x[o] = 1.0
    elif captured is not None:
        x[o + captured.piece_type - 1] = 1.0
    o += 6
    if move.promotion:
        x[o + move.promotion - 1] = 1.0
    o += 5
    x[o] = float(board.is_capture(move))
    x[o + 1] = 0.0  # gives_check deliberately unavailable in the competition runtime
    x[o + 2] = float(board.is_castling(move))
    x[o + 3] = float(board.is_en_passant(move))
    return x


class Policy(nn.Module):
    def __init__(self, hidden: int = 64):
        super().__init__()
        self.board = nn.Sequential(nn.Linear(BOARD_FEATURES, hidden), nn.ReLU())
        self.move = nn.Sequential(nn.Linear(MOVE_FEATURES, hidden), nn.ReLU())
        self.head = nn.Sequential(nn.Linear(hidden * 2, hidden), nn.ReLU(), nn.Linear(hidden, 1))

    def score(self, board_x: torch.Tensor, move_x: torch.Tensor) -> torch.Tensor:
        b = self.board(board_x)
        m = self.move(move_x)
        if b.ndim == 1:
            b = b.unsqueeze(0).expand(move_x.shape[0], -1)
        return self.head(torch.cat((b, m), dim=-1)).squeeze(-1)


def load_records(path: Path):
    rows = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        try:
            board = chess.Board(r["fen"])
        except ValueError:
            continue
        legal = {m.uci() for m in board.legal_moves}
        candidates = []
        for c in r.get("candidates", []):
            move = str(c["move"])
            if move in legal:
                candidates.append((move, int(c["score"])))
        if candidates:
            candidates.sort(key=lambda item: -item[1])
            rows.append((str(r.get("split", "train")), r["fen"], candidates))
    return rows


def soft_target(legal, candidates, temperature: float, max_gap: float) -> torch.Tensor:
    target = torch.zeros(len(legal), dtype=torch.float32)
    best = candidates[0][1]
    by_move = {m: i for i, m in enumerate(legal)}
    indexes = []
    gaps = []
    for move, score in candidates:
        idx = by_move.get(move)
        if idx is None:
            continue
        indexes.append(idx)
        gaps.append(max(-max_gap, float(score - best)) / temperature)
    weights = torch.softmax(torch.tensor(gaps, dtype=torch.float32), dim=0)
    for idx, weight in zip(indexes, weights, strict=True):
        target[idx] = weight
    return target


def evaluate(model: Policy, rows, split: str):
    model.eval()
    total = top1 = top3 = teacher3_hits = 0
    mrr = 0.0
    with torch.no_grad():
        for s, fen, candidates in rows:
            if s != split:
                continue
            board = chess.Board(fen)
            legal = list(board.legal_moves)
            bx = torch.from_numpy(board_features(board))
            mx = torch.from_numpy(np.stack([move_features(board, m) for m in legal]))
            order = torch.argsort(model.score(bx, mx), descending=True).tolist()
            teacher_best = candidates[0][0]
            rank = next(i for i, j in enumerate(order) if legal[j].uci() == teacher_best)
            predicted3 = {legal[j].uci() for j in order[:3]}
            teacher3 = {m for m, _ in candidates[:3]}
            total += 1
            top1 += rank == 0
            top3 += rank < 3
            teacher3_hits += len(predicted3 & teacher3)
            mrr += 1.0 / (rank + 1)
    return {
        "records": total,
        "top1": top1 / max(1, total),
        "top3": top3 / max(1, total),
        "mrr": mrr / max(1, total),
        "mean_teacher_top3_overlap": teacher3_hits / max(1, total),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--temperature", type=float, default=60.0)
    ap.add_argument("--max-gap", type=float, default=600.0)
    ap.add_argument("--seed", type=int, default=20260908)
    args = ap.parse_args()
    torch.manual_seed(args.seed)
    np.random.seed(args.seed)
    torch.set_num_threads(1)
    rows = load_records(args.teacher)
    train = [r for r in rows if r[0] == "train"]
    model = Policy(args.hidden)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-5)
    rng = np.random.default_rng(args.seed)
    for epoch in range(1, args.epochs + 1):
        rng.shuffle(train)
        model.train()
        loss_sum = 0.0
        for _, fen, candidates in train:
            board = chess.Board(fen)
            legal_moves = list(board.legal_moves)
            legal_uci = [m.uci() for m in legal_moves]
            bx = torch.from_numpy(board_features(board))
            mx = torch.from_numpy(np.stack([move_features(board, m) for m in legal_moves]))
            logits = model.score(bx, mx)
            target = soft_target(legal_uci, candidates, args.temperature, args.max_gap)
            loss = -(target * torch.log_softmax(logits, dim=0)).sum()
            opt.zero_grad(); loss.backward(); opt.step(); loss_sum += float(loss)
        val = evaluate(model, rows, "validation")
        print(json.dumps({"epoch": epoch, "mean_loss": loss_sum / max(1, len(train)), "validation": val}), flush=True)
    metrics = {s: evaluate(model, rows, s) for s in ("train", "validation", "holdout")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    torch.jit.script(model.eval()).save(str(args.output))
    meta = {
        "hidden": args.hidden,
        "records": len(rows),
        "metrics": metrics,
        "board_features": BOARD_FEATURES,
        "move_features": MOVE_FEATURES,
        "temperature": args.temperature,
        "max_gap": args.max_gap,
    }
    args.output.with_suffix(".json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    print("FINAL", json.dumps(meta, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
