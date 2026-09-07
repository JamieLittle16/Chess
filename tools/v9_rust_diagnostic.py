from __future__ import annotations

import argparse
import io
import json
import queue
import statistics
import subprocess
import sys
import threading
import time
from collections import Counter, deque
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

import chess
import chess.engine
import chess.pgn

INIT_BUDGET_S = 90.0
WATCHDOG_GRACE_MS = 500
PLY_CAP = 240
FAILED_TERMINATIONS = {"candidate_crash", "candidate_flag", "candidate_illegal", "candidate_init", "rust_crash", "rust_flag", "rust_illegal", "rust_init"}
RESULT_HEADERS = {"white": "1-0", "black": "0-1", "draw": "1/2-1/2", "void": "*"}
FORCING_CLASSES = {"tactical/capture", "forcing-check", "promotion"}


@dataclass
class GameOutcome:
    result: str
    termination: str
    pgn: str
    timings: list[dict]
    final_fen: str
    plies: int
    white_clock_ms: float
    black_clock_ms: float


class CandidateFailure(RuntimeError):
    pass


class CandidateAgent:
    def __init__(self, runner: Path, directory: Path) -> None:
        self.command = [sys.executable, str(runner.resolve()), str(directory.resolve())]
        self.process: subprocess.Popen[str] | None = None
        self.lines: queue.Queue[str | None] = queue.Queue()
        self.stderr_tail: deque[str] = deque(maxlen=80)
        self.threads: list[threading.Thread] = []

    def _forward_stdout(self, stream: TextIO) -> None:
        try:
            for line in stream:
                self.lines.put(line.rstrip("\n"))
        finally:
            self.lines.put(None)

    def _forward_stderr(self, stream: TextIO) -> None:
        for line in stream:
            self.stderr_tail.append(line.rstrip("\n"))

    def start(self) -> None:
        self.process = subprocess.Popen(
            self.command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert self.process.stdout and self.process.stderr
        self.threads = [
            threading.Thread(target=self._forward_stdout, args=(self.process.stdout,), daemon=True),
            threading.Thread(target=self._forward_stderr, args=(self.process.stderr,), daemon=True),
        ]
        for thread in self.threads:
            thread.start()
        line = self._get_line(INIT_BUDGET_S)
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise CandidateFailure(f"candidate_init: bad ready line {line!r}") from exc
        if not isinstance(payload, dict) or payload.get("ready") is not True:
            raise CandidateFailure(f"candidate_init: bad ready payload {payload!r}")

    def _get_line(self, timeout_s: float) -> str:
        try:
            line = self.lines.get(timeout=max(0.01, timeout_s))
        except queue.Empty as exc:
            raise CandidateFailure("candidate_flag: protocol timeout") from exc
        if line is None:
            tail = "\n".join(self.stderr_tail)
            raise CandidateFailure(f"candidate_crash: protocol closed\n{tail}")
        return line

    def move(self, fen: str, time_left_ms: int) -> str:
        if self.process is None or self.process.stdin is None:
            raise CandidateFailure("candidate_crash: process unavailable")
        if self.process.poll() is not None:
            raise CandidateFailure("candidate_crash: process exited")
        request = json.dumps({"fen": fen, "time_left_ms": max(0, int(time_left_ms))})
        try:
            self.process.stdin.write(request + "\n")
            self.process.stdin.flush()
        except BrokenPipeError as exc:
            raise CandidateFailure("candidate_crash: broken pipe") from exc
        line = self._get_line((max(0, time_left_ms) + WATCHDOG_GRACE_MS) / 1000.0)
        try:
            payload = json.loads(line)
        except Exception as exc:
            raise CandidateFailure(f"candidate_illegal: malformed response {line!r}") from exc
        move = payload.get("move") if isinstance(payload, dict) else None
        if not isinstance(move, str):
            raise CandidateFailure(f"candidate_illegal: malformed move payload {payload!r}")
        return move

    def stop(self) -> None:
        if self.process is None:
            return
        proc = self.process
        self.process = None
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.terminate()
        for thread in self.threads:
            thread.join(timeout=0.2)
        self.threads = []


class RustAgent:
    def __init__(self, engine_path: Path) -> None:
        try:
            self.engine = chess.engine.SimpleEngine.popen_uci(str(engine_path.resolve()), timeout=30.0)
        except Exception as exc:
            raise RuntimeError(f"rust_init: {exc}") from exc

    def move(self, board: chess.Board, clocks: dict[chess.Color, float], increment_ms: int) -> str:
        limit = chess.engine.Limit(
            white_clock=max(0.001, clocks[chess.WHITE] / 1000.0),
            black_clock=max(0.001, clocks[chess.BLACK] / 1000.0),
            white_inc=max(0.0, increment_ms / 1000.0),
            black_inc=max(0.0, increment_ms / 1000.0),
        )
        result = self.engine.play(board, limit)
        if result.move is None:
            raise RuntimeError("rust_crash: engine returned no move")
        return result.move.uci()

    def stop(self) -> None:
        try:
            self.engine.quit()
        except Exception:
            try:
                self.engine.close()
            except Exception:
                pass


def side_name(colour: chess.Color) -> str:
    return "white" if colour == chess.WHITE else "black"


def legal_move(board: chess.Board, uci: str) -> chess.Move | None:
    try:
        move = chess.Move.from_uci(uci)
    except ValueError:
        return None
    return move if move in board.legal_moves else None


def flagged_result(board: chess.Board, mover: chess.Color) -> str:
    return "draw" if board.has_insufficient_material(not mover) else side_name(not mover)


def make_pgn(board: chess.Board, result: str, termination: str, white_name: str, black_name: str, event: str, round_name: str) -> str:
    game = chess.pgn.Game.from_board(board)
    game.headers["White"] = white_name
    game.headers["Black"] = black_name
    game.headers["Event"] = event
    game.headers["Round"] = round_name
    game.headers["Result"] = RESULT_HEADERS[result]
    game.headers["Termination"] = termination
    return str(game)


def play_game(
    candidate_dir: Path,
    runner: Path,
    rust_path: Path,
    start_fen: str,
    candidate_white: bool,
    base_ms: int,
    increment_ms: int,
    opening_index: int,
) -> GameOutcome:
    board = chess.Board(start_fen)
    clocks = {chess.WHITE: float(base_ms), chess.BLACK: float(base_ms)}
    timings: list[dict] = []
    candidate = CandidateAgent(runner, candidate_dir)
    rust: RustAgent | None = None
    white_name = "V9" if candidate_white else "Rust"
    black_name = "Rust" if candidate_white else "V9"
    event = f"V9 vs Rust {base_ms}+{increment_ms} diagnostic"
    round_name = f"{opening_index}.{'1' if candidate_white else '2'}"

    try:
        try:
            candidate.start()
        except CandidateFailure:
            result = "black" if candidate_white else "white"
            return GameOutcome(result, "candidate_init", make_pgn(board, result, "candidate_init", white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])
        try:
            rust = RustAgent(rust_path)
        except Exception:
            result = "white" if candidate_white else "black"
            return GameOutcome(result, "rust_init", make_pgn(board, result, "rust_init", white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])

        while True:
            finish = board.outcome()
            if finish is not None:
                result = "draw" if finish.winner is None else side_name(finish.winner)
                term = finish.termination.name.lower()
                return GameOutcome(result, term, make_pgn(board, result, term, white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])
            if board.is_repetition(3):
                return GameOutcome("draw", "threefold_repetition", make_pgn(board, "draw", "threefold_repetition", white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])
            if board.is_fifty_moves():
                return GameOutcome("draw", "fifty_moves", make_pgn(board, "draw", "fifty_moves", white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])
            if board.ply() >= PLY_CAP:
                return GameOutcome("draw", "ply_cap", make_pgn(board, "draw", "ply_cap", white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])

            mover = board.turn
            mover_name = "V9" if (mover == chess.WHITE) == candidate_white else "Rust"
            before = clocks[mover]
            fen_before = board.fen()
            started = time.monotonic()
            try:
                if mover_name == "V9":
                    uci = candidate.move(fen_before, int(before))
                else:
                    assert rust is not None
                    uci = rust.move(board, clocks, increment_ms)
            except CandidateFailure as exc:
                elapsed = (time.monotonic() - started) * 1000.0
                clocks[mover] -= elapsed
                result = side_name(not mover)
                term = "candidate_flag" if "candidate_flag" in str(exc) else "candidate_crash"
                return GameOutcome(result, term, make_pgn(board, result, term, white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])
            except Exception:
                elapsed = (time.monotonic() - started) * 1000.0
                clocks[mover] -= elapsed
                result = side_name(not mover)
                term = "rust_crash"
                return GameOutcome(result, term, make_pgn(board, result, term, white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])

            elapsed = (time.monotonic() - started) * 1000.0
            clocks[mover] -= elapsed
            if clocks[mover] < 0:
                result = flagged_result(board, mover)
                term = "candidate_flag" if mover_name == "V9" else "rust_flag"
                return GameOutcome(result, term, make_pgn(board, result, term, white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])

            move = legal_move(board, uci)
            if move is None:
                result = side_name(not mover)
                term = "candidate_illegal" if mover_name == "V9" else "rust_illegal"
                return GameOutcome(result, term, make_pgn(board, result, term, white_name, black_name, event, round_name), timings, board.fen(), board.ply(), clocks[chess.WHITE], clocks[chess.BLACK])

            timings.append(
                {
                    "ply": board.ply() + 1,
                    "player": mover_name,
                    "move": move.uci(),
                    "elapsed_ms": round(elapsed, 3),
                    "clock_before_ms": round(before, 3),
                    "clock_after_move_ms": round(clocks[mover], 3),
                    "fen": fen_before,
                }
            )
            board.push(move)
            clocks[mover] += increment_ms
    finally:
        candidate.stop()
        if rust is not None:
            rust.stop()


def opening_fens(path: Path, start: int, count: int) -> list[str]:
    all_fens: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        board = chess.Board(line)
        if board.outcome() is None:
            all_fens.append(board.fen())
    selected = all_fens[start : start + count]
    if len(selected) != count:
        raise ValueError(f"requested openings [{start}, {start + count}) but suite only yielded {len(all_fens)} playable positions")
    return selected


def candidate_result(result: str, candidate_white: bool) -> str:
    if result in {"draw", "void"}:
        return "draw"
    return "win" if ((result == "white") == candidate_white) else "loss"


def percentile95(values: list[int]) -> int | None:
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, int(round(0.95 * (len(values) - 1))))]


def cp(score: chess.engine.PovScore, pov: chess.Color) -> int:
    value = score.pov(pov).score(mate_score=100000)
    return int(value if value is not None else 0)


def is_passed_pawn(board: chess.Board, square: chess.Square, colour: chess.Color) -> bool:
    file = chess.square_file(square)
    rank = chess.square_rank(square)
    enemy = board.pieces(chess.PAWN, not colour)
    for enemy_sq in enemy:
        ef = chess.square_file(enemy_sq)
        er = chess.square_rank(enemy_sq)
        if abs(ef - file) > 1:
            continue
        if colour == chess.WHITE and er > rank:
            return False
        if colour == chess.BLACK and er < rank:
            return False
    return True


def classify(board: chess.Board, move: chess.Move) -> str:
    piece = board.piece_at(move.from_square)
    if move.promotion:
        return "promotion"
    if board.is_capture(move):
        return "tactical/capture"
    if board.gives_check(move):
        return "forcing-check"
    if board.is_castling(move):
        return "castling/king-safety"
    if piece and piece.piece_type == chess.PAWN:
        if is_passed_pawn(board, move.to_square, piece.color):
            rel_rank = chess.square_rank(move.to_square) if piece.color else 7 - chess.square_rank(move.to_square)
            if rel_rank >= 4:
                return "passed-pawn"
        rel_rank = chess.square_rank(move.to_square) if piece.color else 7 - chess.square_rank(move.to_square)
        if rel_rank >= 5:
            return "advanced-pawn"
        return "pawn-structure"
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    nonpawns = sum(len(board.pieces(pt, colour)) for pt in range(2, 6) for colour in (chess.WHITE, chess.BLACK))
    if queens == 0 and nonpawns <= 4:
        return "endgame-technique"
    if piece and piece.piece_type == chess.KING:
        return "king-safety"
    return "quiet/positional"


def configure_stockfish(engine: chess.engine.SimpleEngine) -> None:
    options = engine.options
    config = {}
    if "Threads" in options:
        config["Threads"] = 1
    if "Hash" in options:
        config["Hash"] = 128
    if config:
        engine.configure(config)


def annotate(pgn_path: Path, stockfish_path: Path, output: Path, nodes: int) -> dict:
    losses: dict[str, list[int]] = {"V9": [], "Rust": []}
    error_classes: dict[str, Counter[str]] = {"V9": Counter(), "Rust": Counter()}
    best_classes: dict[str, Counter[str]] = {"V9": Counter(), "Rust": Counter()}
    missed_tactical = Counter()
    rows: list[dict] = []
    repetitions: list[dict] = []
    engine = chess.engine.SimpleEngine.popen_uci(str(stockfish_path.resolve()), timeout=30.0)
    configure_stockfish(engine)
    try:
        with pgn_path.open() as handle:
            game_index = 0
            while True:
                game = chess.pgn.read_game(handle)
                if game is None:
                    break
                game_index += 1
                board = game.board()
                moves = list(game.mainline_moves())
                for ply, move in enumerate(moves, 1):
                    mover = "V9" if ((board.turn and game.headers.get("White") == "V9") or ((not board.turn) and game.headers.get("Black") == "V9")) else "Rust"
                    pov = board.turn
                    best_info = engine.analyse(board, chess.engine.Limit(nodes=nodes))
                    best_cp = cp(best_info["score"], pov)
                    pv = best_info.get("pv", [])
                    best_move = pv[0] if pv else None
                    if best_move == move:
                        actual_cp = best_cp
                    else:
                        actual_info = engine.analyse(board, chess.engine.Limit(nodes=nodes), root_moves=[move])
                        actual_cp = cp(actual_info["score"], pov)
                    loss = max(0, best_cp - actual_cp)
                    losses[mover].append(loss)
                    played_class = classify(board, move)
                    best_class = classify(board, best_move) if best_move is not None else "unknown"
                    if loss >= 80:
                        error_classes[mover][played_class] += 1
                        best_classes[mover][best_class] += 1
                        if best_class in FORCING_CLASSES and played_class not in FORCING_CLASSES:
                            missed_tactical[mover] += 1
                    if loss >= 40:
                        rows.append(
                            {
                                "game": game_index,
                                "ply": ply,
                                "player": mover,
                                "fen": board.fen(),
                                "move": move.uci(),
                                "best": best_move.uci() if best_move else None,
                                "loss_cp": loss,
                                "best_cp": best_cp,
                                "played_cp": actual_cp,
                                "played_class": played_class,
                                "best_class": best_class,
                            }
                        )
                    board.push(move)

                if game.headers.get("Termination") == "threefold_repetition":
                    candidate_colour = chess.WHITE if game.headers.get("White") == "V9" else chess.BLACK
                    final_info = engine.analyse(board, chess.engine.Limit(nodes=max(nodes, 20000)))
                    repetitions.append(
                        {
                            "game": game_index,
                            "candidate_eval_cp": cp(final_info["score"], candidate_colour),
                            "final_fen": board.fen(),
                            "last_moves": [move.uci() for move in moves[-10:]],
                        }
                    )
    finally:
        engine.quit()

    rows.sort(key=lambda row: row["loss_cp"], reverse=True)
    summary: dict[str, dict] = {}
    for player, values in losses.items():
        summary[player] = {
            "moves": len(values),
            "mean_loss_cp": round(sum(values) / len(values), 2) if values else None,
            "median_loss_cp": statistics.median(values) if values else None,
            "p95_loss_cp": percentile95(values),
            "inaccuracies_40": sum(value >= 40 for value in values),
            "mistakes_80": sum(value >= 80 for value in values),
            "blunders_200": sum(value >= 200 for value in values),
            "missed_tactical_80": missed_tactical[player],
            "played_error_classes_80cp": dict(error_classes[player]),
            "stockfish_best_classes_80cp": dict(best_classes[player]),
        }
    result = {"summary": summary, "top_swings": rows[:60], "repetition_audit": repetitions}
    output.write_text(json.dumps(result, indent=2))
    return result


def run(args: argparse.Namespace) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    fens = opening_fens(args.openings, args.opening_start, args.opening_count)
    pgn_path = args.out_dir / "v9-vs-rust.pgn"
    pgn_path.write_text("")
    games: list[dict] = []
    wins = draws = losses_count = 0
    terminations: Counter[str] = Counter()

    for local_index, fen in enumerate(fens):
        opening_index = args.opening_start + local_index + 1
        for candidate_white in (True, False):
            outcome = play_game(
                args.agent,
                args.runner,
                args.engine,
                fen,
                candidate_white,
                args.base_ms,
                args.increment_ms,
                opening_index,
            )
            result = candidate_result(outcome.result, candidate_white)
            wins += result == "win"
            draws += result == "draw"
            losses_count += result == "loss"
            terminations[outcome.termination] += 1
            candidate_times = [row["elapsed_ms"] for row in outcome.timings if row["player"] == "V9"]
            rust_times = [row["elapsed_ms"] for row in outcome.timings if row["player"] == "Rust"]
            record = {
                "opening_index": opening_index,
                "candidate_white": candidate_white,
                "candidate_result": result,
                "result": outcome.result,
                "termination": outcome.termination,
                "plies": outcome.plies,
                "final_fen": outcome.final_fen,
                "white_clock_ms": round(outcome.white_clock_ms, 3),
                "black_clock_ms": round(outcome.black_clock_ms, 3),
                "candidate_mean_move_ms": round(sum(candidate_times) / len(candidate_times), 3) if candidate_times else None,
                "rust_mean_move_ms": round(sum(rust_times) / len(rust_times), 3) if rust_times else None,
                "timings": outcome.timings,
            }
            games.append(record)
            with pgn_path.open("a") as handle:
                handle.write(outcome.pgn + "\n\n")
            colour = "W" if candidate_white else "B"
            print(f"opening {opening_index:03d} V9-{colour}: {result} by {outcome.termination} ({outcome.plies} ply)", flush=True)

    game_count = len(games)
    match = {
        "games": game_count,
        "wins": wins,
        "draws": draws,
        "losses": losses_count,
        "score": (wins + 0.5 * draws) / game_count if game_count else 0.0,
        "terminations": dict(terminations),
        "opening_start": args.opening_start,
        "opening_count": args.opening_count,
        "base_ms": args.base_ms,
        "increment_ms": args.increment_ms,
    }
    (args.out_dir / "games.json").write_text(json.dumps(games, indent=2))
    annotation = annotate(pgn_path, args.stockfish, args.out_dir / "stockfish-analysis.json", args.analysis_nodes)
    summary = {"match": match, "stockfish": annotation["summary"], "repetition_audit": annotation["repetition_audit"], "top_swings": annotation["top_swings"][:15]}
    (args.out_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2), flush=True)
    if any(term in FAILED_TERMINATIONS for term in terminations):
        print("WARNING: one or more games ended in engine/protocol failure", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--agent", type=Path, required=True)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--stockfish", type=Path, required=True)
    parser.add_argument("--openings", type=Path, required=True)
    parser.add_argument("--opening-start", type=int, default=0)
    parser.add_argument("--opening-count", type=int, default=6)
    parser.add_argument("--base-ms", type=int, default=2500)
    parser.add_argument("--increment-ms", type=int, default=50)
    parser.add_argument("--analysis-nodes", type=int, default=10000)
    parser.add_argument("--out-dir", type=Path, required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
