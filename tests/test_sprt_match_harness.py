from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

HARNESS_PATH = SCRIPTS / "sprt_match_harness.py"
spec = importlib.util.spec_from_file_location("sprt_match_harness", HARNESS_PATH)
assert spec is not None and spec.loader is not None
sprt = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = sprt
spec.loader.exec_module(sprt)


class SprtHarnessTests(unittest.TestCase):
    def _raw_protocol(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "protocol_id": "m6-sprt-test",
            "runner": "fastchess",
            "max_games": 10_000,
            "time_control": "1+0.01",
            "concurrency": 1,
            "seed": 20261203,
            "max_moves": 300,
            "opening_format": "epd",
            "openings_required": True,
            "opening_suite_id": "test-book",
            "opening_sha256": "1" * 64,
            "paired_colour_reversal": True,
            "ponder": False,
            "tablebases": False,
            "evaluation_adjudication": False,
            "sprt": {
                "elo0": 0.0,
                "elo1": 10.0,
                "alpha": 0.05,
                "beta": 0.05,
                "model": "logistic",
            },
            "notes": "unit test",
        }

    def test_protocol_parses_predeclared_bounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sprt.json"
            path.write_text(json.dumps(self._raw_protocol()), encoding="utf-8")
            protocol = sprt.SprtProtocol.from_json(path)
        self.assertEqual(protocol.max_games, 10_000)
        self.assertEqual(protocol.sprt.elo0, 0.0)
        self.assertEqual(protocol.sprt.elo1, 10.0)
        self.assertEqual(protocol.sprt.model, "logistic")
        self.assertEqual(protocol.as_finite_protocol().games, 10_000)

    def test_invalid_sprt_bounds_are_rejected(self) -> None:
        for bounds in [
            sprt.SprtBounds(10.0, 0.0, 0.05, 0.05, "logistic"),
            sprt.SprtBounds(0.0, 10.0, 0.0, 0.05, "logistic"),
            sprt.SprtBounds(0.0, 10.0, 0.05, 1.0, "logistic"),
            sprt.SprtBounds(0.0, 10.0, 0.05, 0.05, "unknown"),
        ]:
            with self.subTest(bounds=bounds):
                with self.assertRaises(sprt.base.HarnessError):
                    bounds.validate()

    def test_fastchess_command_contains_pairing_and_sprt(self) -> None:
        protocol = sprt.SprtProtocol(
            schema_version=1,
            protocol_id="m6-sprt-test",
            runner="fastchess",
            max_games=10_000,
            time_control="1+0.01",
            concurrency=1,
            seed=20261203,
            max_moves=300,
            opening_format="epd",
            openings_required=True,
            opening_suite_id="test-book",
            opening_sha256="1" * 64,
            paired_colour_reversal=True,
            ponder=False,
            tablebases=False,
            evaluation_adjudication=False,
            sprt=sprt.SprtBounds(0.0, 10.0, 0.05, 0.05, "logistic"),
            notes="unit test",
        )
        paths = sprt.base.MatchPaths(
            output_dir=Path("/tmp/results"),
            manifest=Path("/tmp/results/manifest.json"),
            raw_output=Path("/tmp/results/fastchess.stdout.log"),
            pgn=Path("/tmp/results/games.pgn"),
            engine_log=Path("/tmp/results/uci.log"),
        )
        candidate = sprt.base.EngineSpec(
            name="candidate",
            executable=Path("/engines/candidate"),
            directory=Path("/engines"),
            options=("option.Hash=32",),
        )
        reference = sprt.base.EngineSpec(
            name="reference",
            executable=Path("/engines/reference"),
            directory=Path("/engines"),
            options=("option.Hash=32",),
        )
        command = sprt.build_sprt_command(
            fastchess=Path("/tools/fastchess"),
            protocol=protocol,
            candidate=candidate,
            reference=reference,
            paths=paths,
            openings=Path("/books/m6.epd"),
        )
        self.assertEqual(command[command.index("-rounds") + 1], "5000")
        self.assertEqual(command[command.index("-games") + 1], "2")
        self.assertIn("-repeat", command)
        index = command.index("-sprt")
        self.assertEqual(
            command[index + 1 : index + 6],
            ["elo0=0", "elo1=10", "alpha=0.05", "beta=0.05", "model=logistic"],
        )

    def test_schema_rejects_posthoc_unknown_fields(self) -> None:
        raw = self._raw_protocol()
        raw["peek_then_stop"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "sprt.json"
            path.write_text(json.dumps(raw), encoding="utf-8")
            with self.assertRaisesRegex(sprt.base.HarnessError, "unknown keys: peek_then_stop"):
                sprt.SprtProtocol.from_json(path)


if __name__ == "__main__":
    unittest.main()
