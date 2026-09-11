#!/usr/bin/env python3
"""Build high-confidence opening repairs where exact SEE search materially misses SF19."""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

import chess
import chess.engine
import numpy as np

SHARD = int(os.environ["SHARD"])
SHARDS = 6
SF_NODES = 200_000
SEE_CLOCK_MS = 30_000


def fen_from_key(key: str, ply: int) -> str:
    fullmove = ply // 2 + 1
    fen = f"{key} 0 {fullmove}"
    board = chess.Board(fen)
    if board.ply() != ply:
        raise ValueError((key, ply, board.ply(), fen))
    return fen


def score_cp(info: dict, turn: chess.Color) -> int:
    score = info["score"].pov(turn).score(mate_score=100_000)
    if score is None:
        raise RuntimeError("Stockfish returned score without cp/mate value")
    return int(score)


def main() -> None:
    payload = json.loads(Path("/tmp/tree.json").read_text())
    entries: dict[str, str] = payload["entries"]
    ply_map: dict[str, int] = {k: int(v) for k, v in payload["ply"].items()}
    keys = sorted(entries)[SHARD::SHARDS]

    sys.path.insert(0, "/tmp/base")
    with contextlib.redirect_stdout(sys.stderr):
        import agent  # type: ignore

    def reset_agent() -> None:
        agent._GAME_KEYS.clear()
        agent._PENDING_AFTER_OUR_MOVE = None
        agent._LAST_CALL_TIME_LEFT_MS = None
        agent._LAST_GET_MOVE_ELAPSED_MS = None
        agent._CLOCK_OVERHEAD_EMA_MS = 40.0
        agent._CLOCK_FEEDBACK_SAMPLES = 0
        if hasattr(agent, "_BOOK_POST_SEARCH_BOOSTS"):
            agent._BOOK_POST_SEARCH_BOOSTS = 0
        agent._HASH_KEYS.fill(np.uint64(0))
        agent._HASH_MOVES.fill(np.int32(-1))
        agent._TT_TABLE.fill(np.uint64(0))
        agent._QUIET_HISTORY.fill(np.int16(0))

    engine = chess.engine.SimpleEngine.popen_uci(os.environ["STOCKFISH"])
    engine.configure({"Threads": 1, "Hash": 64})
    direct80: dict[str, str] = {}
    root35: dict[str, str] = {}
    records: list[dict[str, object]] = []
    try:
        for index, key in enumerate(keys, 1):
            ply = ply_map[key]
            board = chess.Board(fen_from_key(key, ply))
            sf_move = chess.Move.from_uci(entries[key])
            if sf_move not in board.legal_moves:
                raise RuntimeError(("illegal tree move", key, entries[key]))
            gm_direct = agent._high_confidence_book_move(board)
            if gm_direct is not None:
                records.append({"key": key, "ply": ply, "skip": "gm_direct", "sf": sf_move.uci()})
                continue

            reset_agent()
            see_move = agent.search_position(board, SEE_CLOCK_MS).move
            if see_move == sf_move:
                records.append({"key": key, "ply": ply, "skip": "agree", "sf": sf_move.uci(), "see": see_move.uci()})
                continue

            engine.configure({"Clear Hash": None})
            infos = engine.analyse(
                board,
                chess.engine.Limit(nodes=SF_NODES),
                multipv=2,
                root_moves=[sf_move, see_move],
            )
            if not isinstance(infos, list):
                infos = [infos]
            scores: dict[chess.Move, int] = {}
            for info in infos:
                pv = info.get("pv")
                if pv:
                    scores[pv[0]] = score_cp(info, board.turn)
            if sf_move not in scores or see_move not in scores:
                raise RuntimeError(("missing comparable root score", key, sf_move, see_move, scores))
            delta = scores[sf_move] - scores[see_move]
            rec = {
                "key": key,
                "ply": ply,
                "sf": sf_move.uci(),
                "see": see_move.uci(),
                "sf_cp": scores[sf_move],
                "see_cp": scores[see_move],
                "delta": delta,
            }
            records.append(rec)
            if delta >= 35:
                root35[key] = sf_move.uci()
            if delta >= 80:
                direct80[key] = sf_move.uci()
            print("NODE", SHARD, index, "/", len(keys), "ply", ply, "sf", sf_move.uci(), "see", see_move.uci(), "delta", delta, flush=True)
    finally:
        engine.quit()

    out = {
        "shard": SHARD,
        "sf_nodes": SF_NODES,
        "see_clock_ms": SEE_CLOCK_MS,
        "positions": len(keys),
        "root35": dict(sorted(root35.items())),
        "direct80": dict(sorted(direct80.items())),
        "records": records,
    }
    path = Path(f"/tmp/repair-{SHARD}.json")
    path.write_text(json.dumps(out, sort_keys=True, separators=(",", ":")))
    print("REPAIR_SHARD", SHARD, "positions", len(keys), "root35", len(root35), "direct80", len(direct80), flush=True)


if __name__ == "__main__":
    main()
