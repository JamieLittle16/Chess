from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HARNESS_PATH = REPO_ROOT / "scripts" / "match_harness.py"
PROTOCOL_PATH = REPO_ROOT / "match" / "protocols" / "m3-baseline-v1.json"
OPENINGS_PATH = REPO_ROOT / "match" / "openings" / "m3-uho-lichess-100-v1.epd"
OPENINGS_SHA256 = "599a45efb446e91952d13e79bc7fec8de319e332036a54552a3e8e4af91f9cf1"

spec = importlib.util.spec_from_file_location("match_harness", HARNESS_PATH)
assert spec is not None and spec.loader is not None
harness = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = harness
spec.loader.exec_module(harness)


class MatchHarnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.protocol = harness.Protocol.from_json(PROTOCOL_PATH)

    def test_checked_in_protocol_is_paired_and_conservative(self) -> None:
        protocol = self.protocol
        self.assertEqual(protocol.protocol_id, "m3-baseline-v1")
        self.assertEqual(protocol.games, 200)
        self.assertEqual(protocol.time_control, "10+0.1")
        self.assertEqual(protocol.concurrency, 1)
        self.assertEqual(protocol.seed, 20260906)
        self.assertTrue(protocol.openings_required)
        self.assertEqual(protocol.opening_suite_id, "m3-uho-lichess-100-v1")
        self.assertEqual(protocol.opening_sha256, OPENINGS_SHA256)
        self.assertTrue(protocol.paired_colour_reversal)
        self.assertFalse(protocol.ponder)
        self.assertFalse(protocol.tablebases)
        self.assertFalse(protocol.evaluation_adjudication)

    def test_protocol_schema_rejects_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "protocol.json"
            raw = asdict(self.protocol)
            raw["surprise"] = True
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(harness.HarnessError, "unknown keys: surprise"):
                harness.Protocol.from_json(path)

    def test_protocol_rejects_unpaired_or_score_adjudicated_runs(self) -> None:
        with self.assertRaisesRegex(harness.HarnessError, "positive even integer"):
            replace(self.protocol, games=199).validate()
        with self.assertRaisesRegex(harness.HarnessError, "evaluation-based"):
            replace(self.protocol, evaluation_adjudication=True).validate()
        with self.assertRaisesRegex(harness.HarnessError, "paired colour reversal"):
            replace(self.protocol, paired_colour_reversal=False).validate()
        with self.assertRaisesRegex(harness.HarnessError, "64-character hexadecimal"):
            replace(self.protocol, opening_sha256="not-a-hash").validate()

    def test_engine_options_are_explicit_name_value_pairs(self) -> None:
        self.assertEqual(harness.parse_engine_option("Hash=64"), "option.Hash=64")
        self.assertEqual(
            harness.parse_engine_option("Style=very aggressive"),
            "option.Style=very aggressive",
        )
        for invalid in ["Hash", "=64", "Hash=", "Bad Name=1"]:
            with self.subTest(invalid=invalid):
                with self.assertRaises(harness.HarnessError):
                    harness.parse_engine_option(invalid)

    def test_fastchess_command_pins_pairing_seed_and_raw_evidence(self) -> None:
        paths = harness.MatchPaths(
            output_dir=Path("/tmp/results"),
            manifest=Path("/tmp/results/manifest.json"),
            raw_output=Path("/tmp/results/fastchess.stdout.log"),
            pgn=Path("/tmp/results/games.pgn"),
            engine_log=Path("/tmp/results/uci.log"),
        )
        candidate = harness.EngineSpec(
            name="candidate",
            executable=Path("/engines/candidate"),
            directory=Path("/engines"),
            options=("option.Hash=32",),
        )
        reference = harness.EngineSpec(
            name="reference",
            executable=Path("/engines/reference"),
            directory=Path("/engines"),
            options=(),
        )
        openings = Path("/books/m3.epd")
        command = harness.build_fastchess_command(
            fastchess=Path("/tools/fastchess"),
            protocol=self.protocol,
            candidate=candidate,
            reference=reference,
            paths=paths,
            openings=openings,
        )

        def value_after(flag: str) -> str:
            return command[command.index(flag) + 1]

        self.assertEqual(value_after("-rounds"), "100")
        self.assertEqual(value_after("-games"), "2")
        self.assertIn("-repeat", command)
        self.assertEqual(value_after("-srand"), "20260906")
        self.assertEqual(value_after("-concurrency"), "1")
        self.assertEqual(value_after("-maxmoves"), "300")
        self.assertEqual(value_after("-report"), "penta=true")
        self.assertIn("file=/tmp/results/games.pgn", command)
        self.assertIn("file=/tmp/results/uci.log", command)
        self.assertIn("file=/books/m3.epd", command)
        self.assertIn("format=epd", command)
        self.assertIn("order=random", command)
        self.assertNotIn("-recover", command)
        self.assertNotIn("-resign", command)
        self.assertNotIn("-draw", command)

    def test_hash_identity_is_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "artifact.bin"
            payload = b"qualification-evidence\x00\xff"
            path.write_bytes(payload)
            identity = harness.identify_file(path)
            self.assertEqual(identity.size_bytes, len(payload))
            self.assertEqual(identity.sha256, hashlib.sha256(payload).hexdigest())
            self.assertEqual(Path(identity.path), path.resolve())

    def test_checked_in_opening_suite_matches_protocol_hash(self) -> None:
        self.assertEqual(harness.sha256_file(OPENINGS_PATH), OPENINGS_SHA256)
        self.assertEqual(harness.resolve_openings(OPENINGS_PATH, self.protocol), OPENINGS_PATH.resolve())

    def test_wrong_opening_suite_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "wrong.epd"
            path.write_text("8/8/8/8/8/8/8/K6k w - - 0 1\n", encoding="utf-8")
            with self.assertRaisesRegex(harness.HarnessError, "opening suite hash mismatch"):
                harness.resolve_openings(path, self.protocol)

    def test_output_directory_must_be_new_or_empty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            empty = root / "empty"
            empty.mkdir()
            paths = harness.make_paths(empty)
            self.assertEqual(paths.output_dir, empty.resolve())

            occupied = root / "occupied"
            occupied.mkdir()
            (occupied / "old.txt").write_text("old run", encoding="utf-8")
            with self.assertRaisesRegex(harness.HarnessError, "must be empty"):
                harness.make_paths(occupied)

    def test_missing_required_openings_fails_before_output_creation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._fake_executable(root / "candidate", "candidate")
            reference = self._fake_executable(root / "reference", "reference")
            fastchess = self._fake_executable(root / "fastchess", "fake-fastchess 1.0")
            output = root / "results"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                code = harness.main(
                    [
                        "--candidate",
                        str(candidate),
                        "--reference",
                        str(reference),
                        "--fastchess",
                        str(fastchess),
                        "--output-dir",
                        str(output),
                        "--protocol",
                        str(PROTOCOL_PATH),
                        "--dry-run",
                    ]
                )
            self.assertEqual(code, 2)
            self.assertIn("requires opening suite", stderr.getvalue())
            self.assertFalse(output.exists())

    def test_dry_run_records_hashed_inputs_and_exact_command(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            candidate = self._fake_executable(root / "candidate", "candidate")
            reference = self._fake_executable(root / "reference", "reference")
            fastchess = self._fake_executable(root / "fastchess", "fake-fastchess 1.0")
            output = root / "results"

            stdout = io.StringIO()
            stderr = io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = harness.main(
                    [
                        "--candidate",
                        str(candidate),
                        "--reference",
                        str(reference),
                        "--fastchess",
                        str(fastchess),
                        "--openings",
                        str(OPENINGS_PATH),
                        "--output-dir",
                        str(output),
                        "--protocol",
                        str(PROTOCOL_PATH),
                        "--candidate-option",
                        "Hash=32",
                        "--dry-run",
                    ]
                )

            self.assertEqual(code, 0, stderr.getvalue())
            manifest_path = output / "manifest.json"
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["status"], "dry-run")
            self.assertEqual(manifest["protocol"]["protocol_id"], "m3-baseline-v1")
            self.assertEqual(manifest["protocol"]["opening_suite_id"], "m3-uho-lichess-100-v1")
            self.assertEqual(
                manifest["candidate"]["file"]["sha256"],
                harness.sha256_file(candidate),
            )
            self.assertEqual(
                manifest["reference"]["file"]["sha256"],
                harness.sha256_file(reference),
            )
            self.assertEqual(manifest["openings"]["sha256"], OPENINGS_SHA256)
            self.assertEqual(manifest["runner"]["version_output"], "fake-fastchess 1.0")
            self.assertIn("-repeat", manifest["command"]["argv"])
            self.assertIn("-srand", manifest["command"]["argv"])
            self.assertIn("option.Hash=32", manifest["command"]["argv"])
            self.assertNotIn("-recover", manifest["command"]["argv"])
            self.assertIn("manifest:", stdout.getvalue())

    def test_output_artifact_hashes_are_recorded_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            paths = harness.make_paths(Path(temporary) / "results")
            paths.raw_output.write_text("raw", encoding="utf-8")
            paths.pgn.write_text("[Result \"1/2-1/2\"]\n", encoding="utf-8")
            artifacts = harness.output_artifacts(paths)
            self.assertEqual(
                artifacts["raw_runner_output"]["sha256"],
                harness.sha256_file(paths.raw_output),
            )
            self.assertEqual(
                artifacts["pgn"]["sha256"],
                harness.sha256_file(paths.pgn),
            )
            self.assertIsNone(artifacts["engine_log"])

    @staticmethod
    def _fake_executable(path: Path, output: str) -> Path:
        path.write_text(f"#!/bin/sh\necho '{output}'\n", encoding="utf-8")
        path.chmod(path.stat().st_mode | 0o111)
        return path


if __name__ == "__main__":
    unittest.main()
