#!/usr/bin/env python3
"""Calibrate the packaged Little Gambit V18 agent against Stockfish UCI_Elo.

The runner imports the exact submitted agent once, then simulates independent games from the
repository's frozen UHO EPD suite.  Each game starts with fresh V18 TT/history state while retaining
the already-JIT-compiled code.  Stockfish receives real UCI clocks through python-chess.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import statistics
import sys
import time
from pathlib import Path

import chess
import chess.engine
import chess.pgn
import numpy as np


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def parse_tc(text: str) -> tuple[float, float]:
    base, sep, inc = text.partition("+")
    if not sep:
        raise ValueError("time control must be BASE+INC")
    return float(base), float(inc)


def load_epds(path: Path) -> list[str]:
    rows = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        board = chess.Board(line)
        rows.append(board.fen())
    if not rows:
        raise RuntimeError("no openings found")
    return rows


def reset_agent(agent) -> None:
    agent._GAME_KEYS.clear()
    agent._PENDING_AFTER_OUR_MOVE = None
    agent._LAST_CALL_TIME_LEFT_MS = None
    agent._LAST_GET_MOVE_ELAPSED_MS = None
    agent._CLOCK_OVERHEAD_EMA_MS = 40.0
    agent._CLOCK_FEEDBACK_SAMPLES = 0
    agent._HASH_KEYS.fill(np.uint64(0))
    agent._HASH_MOVES.fill(np.int32(-1))
    agent._TT_TABLE.fill(np.uint64(0))
    agent._QUIET_HISTORY.fill(np.int16(0))


def score_to_elo(score: float) -> float:
    eps = 1e-6
    p = min(1.0 - eps, max(eps, score))
    return 400.0 * math.log10(p / (1.0 - p))


def bootstrap_elo(pair_scores: list[float], seed: int, samples: int = 20000) -> tuple[float, float]:
    if not pair_scores:
        return float("nan"), float("nan")
    rng = random.Random(seed ^ 0xA17E10)
    n = len(pair_scores)
    estimates = []
    for _ in range(samples):
        total = sum(pair_scores[rng.randrange(n)] for _ in range(n))
        estimates.append(score_to_elo(total / (2.0 * n)))
    estimates.sort()
    lo = estimates[int(0.025 * samples)]
    hi = estimates[min(samples - 1, int(0.975 * samples))]
    return lo, hi


def result_for_terminal(board: chess.Board) -> str | None:
    outcome = board.outcome(claim_draw=True)
    return None if outcome is None else outcome.result()


def play_game(*, agent, sf, start_fen: str, v18_color: chess.Color,
              base_s: float, inc_s: float, max_plies: int, game_token: object) -> dict:
    reset_agent(agent)
    board = chess.Board(start_fen)
    clocks = {chess.WHITE: base_s, chess.BLACK: base_s}
    game = chess.pgn.Game()
    game.setup(board)
    game.headers["Event"] = "V18 Stockfish calibration"
    game.headers["White"] = "Little-Gambit-V18" if v18_color == chess.WHITE else "Stockfish-19"
    game.headers["Black"] = "Little-Gambit-V18" if v18_color == chess.BLACK else "Stockfish-19"
    node = game
    v18_times: list[float] = []
    sf_times: list[float] = []
    failure = None

    for ply in range(max_plies):
        terminal = result_for_terminal(board)
        if terminal is not None:
            break
        side = board.turn
        started = time.perf_counter()
        try:
            if side == v18_color:
                uci = agent.get_move(board.fen(), max(1, int(round(clocks[side] * 1000.0))))
                elapsed = time.perf_counter() - started
                v18_times.append(elapsed)
                move = chess.Move.from_uci(uci)
                if move not in board.legal_moves:
                    failure = f"V18 illegal move {uci}"
                    terminal = "0-1" if side == chess.WHITE else "1-0"
                    break
            else:
                limit = chess.engine.Limit(
                    white_clock=max(0.001, clocks[chess.WHITE]),
                    black_clock=max(0.001, clocks[chess.BLACK]),
                    white_inc=inc_s,
                    black_inc=inc_s,
                )
                response = sf.play(board, limit, game=game_token)
                elapsed = time.perf_counter() - started
                sf_times.append(elapsed)
                move = response.move
                if move is None or move not in board.legal_moves:
                    failure = "Stockfish returned no/illegal move"
                    terminal = "0-1" if side == chess.WHITE else "1-0"
                    break
        except Exception as exc:
            elapsed = time.perf_counter() - started
            failure = f"{type(exc).__name__}: {exc}"
            terminal = "0-1" if side == chess.WHITE else "1-0"
            break

        clocks[side] -= elapsed
        if clocks[side] < 0.0:
            failure = f"{'V18' if side == v18_color else 'Stockfish'} flag ({elapsed:.6f}s move)"
            terminal = "0-1" if side == chess.WHITE else "1-0"
            break

        board.push(move)
        node = node.add_variation(move)
        clocks[side] += inc_s
    else:
        terminal = "1/2-1/2"
        failure = "max plies draw"

    if terminal is None:
        terminal = result_for_terminal(board) or "1/2-1/2"
    game.headers["Result"] = terminal
    if failure:
        game.headers["Termination"] = failure[:200]

    if terminal == "1/2-1/2":
        v18_points = 0.5
    elif (terminal == "1-0" and v18_color == chess.WHITE) or (terminal == "0-1" and v18_color == chess.BLACK):
        v18_points = 1.0
    else:
        v18_points = 0.0

    return {
        "result": terminal,
        "v18_points": v18_points,
        "v18_color": "white" if v18_color == chess.WHITE else "black",
        "plies": board.ply(),
        "failure": failure,
        "v18_clock_s": clocks[v18_color],
        "sf_clock_s": clocks[not v18_color],
        "v18_mean_move_s": statistics.fmean(v18_times) if v18_times else 0.0,
        "sf_mean_move_s": statistics.fmean(sf_times) if sf_times else 0.0,
        "pgn": str(game),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine-dir", type=Path, required=True)
    ap.add_argument("--stockfish", type=Path, required=True)
    ap.add_argument("--openings", type=Path, required=True)
    ap.add_argument("--elo", type=int, required=True)
    ap.add_argument("--games", type=int, default=100)
    ap.add_argument("--tc", default="1+0.01")
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--max-plies", type=int, default=600)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    if args.games <= 0 or args.games % 2:
        raise SystemExit("--games must be a positive even number")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    base_s, inc_s = parse_tc(args.tc)
    openings = load_epds(args.openings)
    rng = random.Random(args.seed)
    rng.shuffle(openings)
    needed = args.games // 2
    if needed > len(openings):
        raise SystemExit(f"need {needed} openings but only have {len(openings)}")
    openings = openings[:needed]

    sys.path.insert(0, str(args.engine_dir.resolve()))
    import agent

    sf = chess.engine.SimpleEngine.popen_uci(str(args.stockfish.resolve()))
    sf.configure({"Threads": 1, "Hash": 32, "UCI_LimitStrength": True, "UCI_Elo": args.elo})

    records = []
    pgn_path = args.output_dir / "games.pgn"
    started_all = time.perf_counter()
    try:
        with pgn_path.open("w", encoding="utf-8") as pgn_out:
            for pair_index, fen in enumerate(openings):
                for leg, color in enumerate((chess.WHITE, chess.BLACK)):
                    rec = play_game(
                        agent=agent,
                        sf=sf,
                        start_fen=fen,
                        v18_color=color,
                        base_s=base_s,
                        inc_s=inc_s,
                        max_plies=args.max_plies,
                        game_token=(args.elo, pair_index, leg),
                    )
                    rec["pair"] = pair_index
                    rec["opening_fen"] = fen
                    records.append(rec)
                    pgn_out.write(rec.pop("pgn"))
                    pgn_out.write("\n\n")
                    idx = len(records)
                    w = sum(r["v18_points"] == 1.0 for r in records)
                    d = sum(r["v18_points"] == 0.5 for r in records)
                    l = sum(r["v18_points"] == 0.0 for r in records)
                    print(f"elo={args.elo} game={idx}/{args.games} WDL={w}-{d}-{l}", flush=True)
    finally:
        sf.quit()

    wins = sum(r["v18_points"] == 1.0 for r in records)
    draws = sum(r["v18_points"] == 0.5 for r in records)
    losses = sum(r["v18_points"] == 0.0 for r in records)
    points = sum(float(r["v18_points"]) for r in records)
    score = points / len(records)
    rel_elo = score_to_elo(score)
    pair_scores = [records[2*i]["v18_points"] + records[2*i+1]["v18_points"] for i in range(needed)]
    ci_lo, ci_hi = bootstrap_elo(pair_scores, args.seed)

    summary = {
        "stockfish_uci_elo": args.elo,
        "games": len(records),
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": points,
        "score": score,
        "relative_elo": rel_elo,
        "relative_elo_pair_bootstrap_95": [ci_lo, ci_hi],
        "implied_v18_rating": args.elo + rel_elo,
        "pair_scores": pair_scores,
        "time_control": args.tc,
        "seed": args.seed,
        "elapsed_s": time.perf_counter() - started_all,
        "engine_zip_sha256": sha256_file(args.engine_dir.parent / "v18.zip") if (args.engine_dir.parent / "v18.zip").is_file() else None,
        "stockfish_sha256": sha256_file(args.stockfish),
        "openings_sha256": sha256_file(args.openings),
        "failures": [r["failure"] for r in records if r["failure"]],
    }
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    with (args.output_dir / "games.csv").open("w", newline="", encoding="utf-8") as f:
        fields = ["pair", "v18_color", "result", "v18_points", "plies", "failure", "v18_clock_s", "sf_clock_s", "v18_mean_move_s", "sf_mean_move_s", "opening_fen"]
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for rec in records:
            w.writerow({k: rec.get(k) for k in fields})
    print(json.dumps(summary, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
