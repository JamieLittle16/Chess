#!/usr/bin/env python3
"""Hermetic tests for the offline strength-laboratory substrate."""
from __future__ import annotations

import argparse
import tempfile
import unittest
from pathlib import Path

import chess

from engine_error_replay import classify_depth_response, parse_node_budgets
from generate_nnue_teacher_data import deterministic_split, epd_positions, pgn_positions
from stockfish_lab import loss_bucket, move_kind, phase_label, sha256_file


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

    def test_pgn_positions_share_one_group_for_one_opening_root(self) -> None:
        # Both games deliberately begin from startpos. They model a paired colour-reversed opening:
        # trajectory differences must not let the pair leak across teacher splits.
        pgn = """[Event \"A\"]
[Result \"*\"]

1. e4 e5 2. Nf3 *

[Event \"B\"]
[Result \"*\"]

1. d4 d5 2. c4 *
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "games.pgn"
            renamed = Path(directory) / "renamed-copy.pgn"
            path.write_text(pgn)
            renamed.write_text(pgn)
            source_sha256 = sha256_file(path)
            self.assertEqual(source_sha256, sha256_file(renamed))
            positions = list(pgn_positions(path, source_sha256, 1, 10))
            copied = list(pgn_positions(renamed, source_sha256, 1, 10))

        groups = [group for group, _, _ in positions]
        self.assertEqual(len(positions), 6)
        self.assertEqual(len(set(groups)), 1)
        self.assertEqual(groups, [group for group, _, _ in copied])
        self.assertTrue(groups[0].startswith("root:rnbqkbnr/pppppppp/"))

    def test_epd_distinct_roots_are_path_independent_groups(self) -> None:
        epd = """8/8/8/8/8/8/4K3/7k w - -
8/8/8/8/8/8/3K4/7k b - -
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "positions.epd"
            renamed = Path(directory) / "copy.epd"
            path.write_text(epd)
            renamed.write_text(epd)
            source_sha256 = sha256_file(path)
            positions = list(epd_positions(path, source_sha256))
            copied = list(epd_positions(renamed, source_sha256))

        self.assertEqual(len(positions), 2)
        self.assertNotEqual(positions[0][0], positions[1][0])
        self.assertEqual(
            [group for group, _, _ in positions],
            [group for group, _, _ in copied],
        )
        self.assertTrue(positions[0][0].startswith("root:"))

    def test_pgn_and_epd_same_root_share_cross_source_group(self) -> None:
        pgn = """[Event \"Root only\"]
[Result \"*\"]

*
"""
        epd = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -\n"
        with tempfile.TemporaryDirectory() as directory:
            pgn_path = Path(directory) / "root.pgn"
            epd_path = Path(directory) / "root.epd"
            pgn_path.write_text(pgn)
            epd_path.write_text(epd)
            pgn_group = list(pgn_positions(pgn_path, sha256_file(pgn_path), 0, 0))[0][0]
            epd_group = list(epd_positions(epd_path, sha256_file(epd_path)))[0][0]

        self.assertEqual(pgn_group, epd_group)

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

    def test_error_replay_node_budget_parser_is_strict(self) -> None:
        self.assertEqual(parse_node_budgets("2000, 10000,50000"), (2000, 10000, 50000))
        for invalid in ("", "0,100", "100,-2", "100,100", "500,100", "abc"):
            with self.assertRaises(argparse.ArgumentTypeError, msg=invalid):
                parse_node_budgets(invalid)

    def test_error_replay_classification_only_claims_observed_search_response(self) -> None:
        self.assertEqual(classify_depth_response([120, 70, 20]), "resolved_by_search")
        self.assertEqual(classify_depth_response([180, 145, 110]), "improves_with_search")
        self.assertEqual(classify_depth_response([80, 100, 145]), "worsens_with_search")
        self.assertEqual(
            classify_depth_response([120, 105, 95]),
            "persistent_at_tested_budget",
        )
        with self.assertRaises(ValueError):
            classify_depth_response([])


if __name__ == "__main__":
    unittest.main()
