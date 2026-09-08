#!/usr/bin/env python3
"""Train a tiny root policy student from teacher best-move labels.

The model is deliberately root-only: a compact board embedding plus move-conditioned scorer. It is
trained from engine-labelled positions and is intended only to rank legal root moves; normal search
still verifies every candidate. Runtime cost is therefore paid once per root iteration, not per node.
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
BOARD_FEATURES = PLANES * SQUARES + 5  # pieces + STM + castling
MOVE_FEATURES = 64 + 64 + 6 + 6 + 5 + 4  # from/to one-hot, mover/captured/promo + flags


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
    x[o + 1] = float(board.gives_check(move))
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
        best = r.get("teacher_best_move")
        if not best:
            continue
        b = chess.Board(r["fen"])
        try:
            mv = chess.Move.from_uci(best)
        except ValueError:
            continue
        if mv not in b.legal_moves:
            continue
        rows.append((str(r.get("split", "train")), r["fen"], best))
    return rows


def evaluate(model: Policy, rows, split: str):
    model.eval()
    total = 0; top1 = 0; top3 = 0; mrr = 0.0
    with torch.no_grad():
        for s, fen, best in rows:
            if s != split:
                continue
            b = chess.Board(fen)
            legal = list(b.legal_moves)
            bx = torch.from_numpy(board_features(b))
            mx = torch.from_numpy(np.stack([move_features(b, m) for m in legal]))
            scores = model.score(bx, mx)
            order = torch.argsort(scores, descending=True).tolist()
            rank = next(i for i, j in enumerate(order) if legal[j].uci() == best)
            total += 1; top1 += rank == 0; top3 += rank < 3; mrr += 1.0 / (rank + 1)
    return {"records": total, "top1": top1 / max(1,total), "top3": top3 / max(1,total), "mrr": mrr / max(1,total)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--teacher", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--hidden", type=int, default=64)
    ap.add_argument("--epochs", type=int, default=12)
    ap.add_argument("--seed", type=int, default=20260908)
    args = ap.parse_args()
    torch.manual_seed(args.seed); np.random.seed(args.seed)
    torch.set_num_threads(1)
    rows = load_records(args.teacher)
    train = [r for r in rows if r[0] == "train"]
    model = Policy(args.hidden)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-3, weight_decay=1e-5)
    rng = np.random.default_rng(args.seed)
    for epoch in range(1, args.epochs + 1):
        rng.shuffle(train); model.train(); loss_sum = 0.0
        for _, fen, best in train:
            b = chess.Board(fen); legal = list(b.legal_moves)
            bx = torch.from_numpy(board_features(b))
            mx = torch.from_numpy(np.stack([move_features(b, m) for m in legal]))
            target = next(i for i,m in enumerate(legal) if m.uci() == best)
            logits = model.score(bx, mx).unsqueeze(0)
            loss = nn.functional.cross_entropy(logits, torch.tensor([target]))
            opt.zero_grad(); loss.backward(); opt.step(); loss_sum += float(loss)
        val = evaluate(model, rows, "validation")
        print(json.dumps({"epoch":epoch,"mean_loss":loss_sum/max(1,len(train)),"validation":val}), flush=True)
    metrics = {s:evaluate(model, rows, s) for s in ("train","validation","holdout")}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scripted = torch.jit.script(model.eval())
    scripted.save(str(args.output))
    meta = {"hidden":args.hidden,"records":len(rows),"metrics":metrics,"board_features":BOARD_FEATURES,"move_features":MOVE_FEATURES}
    args.output.with_suffix(".json").write_text(json.dumps(meta, indent=2, sort_keys=True)+"\n")
    print("FINAL", json.dumps(meta, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
