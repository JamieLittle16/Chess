#!/usr/bin/env python3
"""Hermetic tests for the offline strength-laboratory substrate."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import chess

from generate_nnue_teacher_data import deterministic_split, epd_positions, pgn_positions
from stockfish_lab import loss_bucket, move_kind, phase_label


class StrengthLabTests(unittest.TestCase):
    def test_split_is_deterministic_and_group_scoped(self) -> None:
        first = deterministic_split(
            "game:42", salt="test-salt", validation=100, holdout=100
        )
        second = deterministic_split(
            "game:42", salt="test-salt", validation=100, holdout=100
        )
        self.assertEqual(first, second)
        self.assertIn(first, {"train", "validation", "holdout"})

        with self.assertRaises(ValueError):
            deterministic_split("x", salt="s", validation=600, holdout=400)

    def test_pgn_positions_keep_whole_games_in_one_group(self) -> None:
        pgn = """[Event \"A\"]
[Result \"*\"]

1. e4 e5 2. Nf3 *

[Event \"B\"]
[Result \"*\"]

1. d4 d5 2. c4 *
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "games.pgn"
            path.write_text(pgn)
            positions = list(pgn_positions(path, 1, 10))

        groups = [group for group, _, _ in positions]
        self.assertEqual(len(positions), 6)
        self.assertEqual(len(set(groups[:3])), 1)
        self.assertEqual(len(set(groups[3:])), 1)
        self.assertNotEqual(groups[0], groups[3])

    def test_epd_lines_are_distinct_groups(self) -> None:
        epd = """8/8/8/8/8/8/4K3/7k w - -
8/8/8/8/8/8/3K4/7k b - -
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "positions.epd"
            path.write_text(epd)
            positions = list(epd_positions(path))

        self.assertEqual(len(positions), 2)
        self.assertNotEqual(positions[0][0], positions[1][0])

    def test_move_classification_is_factual(self) -> None:
        board = chess.Board()
        self.assertEqual(move_kind(board, chess.Move.from_uci("e2e4")), "quiet")

        board = chess.Board("7k/4r3/8/8/8/8/4Q3/7K w - - 0 1")
        self.assertEqual(move_kind(board, chess.Move.from_uci("e2e7")), "capture")

        board = chess.Board("7k/P7/8/8/8/8/8/7K w - - 0 1")
        self.assertEqual(move_kind(board, chess.Move.from_uci("a7a8q")), "promotion")

        board = chess.Board("7k/8/8/8/8/8/4Q3/7K w - - 0 1")
        self.assertEqual(move_kind(board, chess.Move.from_uci("e2e8")), "quiet_check")

    def test_phase_and_loss_buckets_are_stable(self) -> None:
        self.assertEqual(phase_label(chess.Board()), "opening_or_early_middlegame")
        self.assertEqual(
            phase_label(chess.Board("7k/8/8/8/8/8/8/7K w - - 0 1")),
            "endgame",
        )
        self.assertEqual(loss_bucket(29), "small")
        self.assertEqual(loss_bucket(30), "inaccuracy")
        self.assertEqual(loss_bucket(80), "mistake")
        self.assertEqual(loss_bucket(150), "blunder")
        self.assertEqual(loss_bucket(300), "severe_blunder")


if __name__ == "__main__":
    unittest.main()
