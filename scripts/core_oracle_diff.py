#!/usr/bin/env python3
"""Differentially qualify chess-core against the independent python-chess rules engine."""

from __future__ import annotations

import argparse
import random
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import chess

SEEDS = (
    0x243F6A8885A308D3,
    0x13198A2E03707344,
    0xA4093822299F31D0,
    0x082EFA98EC4E6C89,
    0x452821E638D01377,
    0xBE5466CF34E90C6C,
    0xC0AC29B7C97C50DD,
    0x3F84D5B5B5470917,
    0x9216D5D98979FB1B,
    0xD1310BA698DFB5AC,
    0x2FFD72DBD01ADFB7,
    0xB8E1AFED6A267E96,
    0xBA7C9045F12C7F99,
    0x24A19947B3916CF7,
    0x0801F2E2858EFC16,
    0x636920D871574E69,
)

CURATED_FENS = (
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
    "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
    "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
    "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10",
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "8/8/8/3pP3/8/8/8/K6k w - d6 0 1",
    "k7/8/8/4KPpr/8/8/8/8 w - g6 0 1",
    "7k/P7/8/8/8/8/8/K7 w - - 0 1",
    "1r5k/P7/8/8/8/8/8/K7 w - - 0 1",
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
    "4r2k/8/8/8/8/8/6Q1/4K3 w - - 0 1",
)


@dataclass(frozen=True)
class Query:
    request: str
    expected: str
    label: str


def exact_fen(board: chess.Board) -> str:
    return board.fen(en_passant="fen")


def deterministic_positions(target: int) -> list[str]:
    if target < len(CURATED_FENS):
        raise ValueError(f"target must be at least {len(CURATED_FENS)}")

    positions: list[str] = []
    seen: set[str] = set()

    def add(board: chess.Board) -> None:
        fen = exact_fen(board)
        if fen not in seen:
            seen.add(fen)
            positions.append(fen)

    for fen in CURATED_FENS:
        board = chess.Board(fen)
        if not board.is_valid():
            raise AssertionError(f"curated oracle FEN is invalid: {fen}")
        add(board)

    round_index = 0
    while len(positions) < target:
        seed = SEEDS[round_index % len(SEEDS)] ^ (
            round_index * 0x9E3779B97F4A7C15
        )
        rng = random.Random(seed)
        board = chess.Board()
        add(board)

        for ply in range(160):
            legal = sorted(board.legal_moves, key=lambda move: move.uci())
            if not legal:
                break
            board.push(legal[rng.randrange(len(legal))])

            # Retain every second position plus tactically/specially interesting states.
            if (
                ply % 2 == 1
                or board.is_check()
                or board.ep_square is not None
                or any(move.promotion for move in board.legal_moves)
            ):
                add(board)
                if len(positions) >= target:
                    return positions[:target]

        round_index += 1
        if round_index > target * 4:
            raise RuntimeError("failed to generate enough unique deterministic positions")

    return positions[:target]


def python_perft(board: chess.Board, depth: int) -> int:
    if depth == 0:
        return 1
    if depth == 1:
        return board.legal_moves.count()

    nodes = 0
    for move in list(board.legal_moves):
        board.push(move)
        nodes += python_perft(board, depth - 1)
        board.pop()
    return nodes


def build_queries(
    positions: list[str], transition_positions: int, perft_positions: int
) -> list[Query]:
    queries: list[Query] = []

    for index, fen in enumerate(positions):
        board = chess.Board(fen)
        legal = sorted(move.uci() for move in board.legal_moves)
        queries.append(
            Query(
                request=f"moves\t{fen}",
                expected="OK\t" + ",".join(legal),
                label=f"legal moves position {index}: {fen}",
            )
        )

        if index < transition_positions:
            for uci in legal:
                child = board.copy(stack=False)
                child.push_uci(uci)
                queries.append(
                    Query(
                        request=f"move\t{fen}\t{uci}",
                        expected="OK\t" + exact_fen(child),
                        label=f"transition position {index} move {uci}: {fen}",
                    )
                )

        if index < perft_positions:
            depth = 2
            queries.append(
                Query(
                    request=f"perft\t{fen}\t{depth}",
                    expected=f"OK\t{python_perft(board.copy(stack=False), depth)}",
                    label=f"perft position {index} depth {depth}: {fen}",
                )
            )

    return queries


def run_bridge(bridge: Path, queries: Iterable[Query]) -> tuple[list[Query], list[str]]:
    materialized = list(queries)
    payload = "\n".join(query.request for query in materialized) + "\n"
    completed = subprocess.run(
        [str(bridge)],
        input=payload,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"oracle bridge exited {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    return materialized, completed.stdout.splitlines()


def qualify(
    bridge: Path, position_count: int, transition_positions: int, perft_positions: int
) -> None:
    if transition_positions > position_count or perft_positions > position_count:
        raise ValueError("transition/perft position counts cannot exceed total positions")

    positions = deterministic_positions(position_count)
    queries = build_queries(positions, transition_positions, perft_positions)
    materialized, answers = run_bridge(bridge, queries)

    if len(answers) != len(materialized):
        raise AssertionError(
            f"bridge returned {len(answers)} lines for {len(materialized)} queries"
        )

    for query, actual in zip(materialized, answers, strict=True):
        if actual != query.expected:
            raise AssertionError(
                f"external-oracle mismatch: {query.label}\n"
                f"request:  {query.request}\n"
                f"expected: {query.expected}\n"
                f"actual:   {actual}"
            )

    move_queries = position_count
    transition_queries = sum(
        chess.Board(fen).legal_moves.count()
        for fen in positions[:transition_positions]
    )
    print(
        "external chess-rule oracle qualification passed: "
        f"positions={position_count} move_sets={move_queries} "
        f"transitions={transition_queries} perft_depth2={perft_positions} "
        f"total_queries={len(materialized)}"
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--positions", type=int, default=512)
    parser.add_argument("--transition-positions", type=int, default=192)
    parser.add_argument("--perft-positions", type=int, default=64)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    qualify(
        bridge=args.bridge.resolve(),
        position_count=args.positions,
        transition_positions=args.transition_positions,
        perft_positions=args.perft_positions,
    )


if __name__ == "__main__":
    main()
