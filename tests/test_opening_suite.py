from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATOR_PATH = REPO_ROOT / "scripts" / "build_opening_suite.py"
OPENINGS_PATH = REPO_ROOT / "match" / "openings" / "m3-uho-lichess-100-v1.epd"
METADATA_PATH = REPO_ROOT / "match" / "openings" / "m3-uho-lichess-100-v1.json"

spec = importlib.util.spec_from_file_location("build_opening_suite", GENERATOR_PATH)
assert spec is not None and spec.loader is not None
generator = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = generator
spec.loader.exec_module(generator)


class OpeningSuiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = json.loads(METADATA_PATH.read_text(encoding="utf-8"))
        self.lines = OPENINGS_PATH.read_text(encoding="utf-8").splitlines()

    def test_metadata_matches_generator_contract(self) -> None:
        metadata = self.metadata
        self.assertEqual(metadata["suite_id"], generator.SUITE_ID)
        self.assertEqual(metadata["positions"], generator.SELECTION_COUNT)
        self.assertEqual(metadata["sha256"], generator.SUITE_SHA256)
        self.assertEqual(metadata["source"]["repository"], generator.SOURCE_REPOSITORY)
        self.assertEqual(metadata["source"]["commit"], generator.SOURCE_COMMIT)
        self.assertEqual(metadata["source"]["git_blob_sha"], generator.SOURCE_GIT_BLOB_SHA)
        self.assertEqual(metadata["source"]["archive_sha256"], generator.SOURCE_ARCHIVE_SHA256)
        self.assertEqual(metadata["source"]["sri_sha384_base64"], generator.SOURCE_SRI_SHA384_BASE64)
        self.assertEqual(metadata["source"]["license"], "CC0-1.0")

    def test_vendored_bytes_match_pinned_hash_and_count(self) -> None:
        payload = OPENINGS_PATH.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(), generator.SUITE_SHA256)
        self.assertEqual(len(self.lines), generator.SELECTION_COUNT)
        self.assertEqual(len(set(self.lines)), generator.SELECTION_COUNT)
        self.assertTrue(payload.endswith(b"\n"))

    def test_positions_are_in_stable_rank_order(self) -> None:
        seed = generator.SELECTION_SEED.encode("ascii") + b"\0"
        ranks = [hashlib.sha256(seed + line.encode("utf-8")).hexdigest() for line in self.lines]
        self.assertEqual(ranks, sorted(ranks))
        self.assertEqual(
            ranks[-1],
            self.metadata["selection"]["highest_selected_rank_sha256"],
        )
        self.assertEqual(
            len(self.metadata["selection"]["selected_source_lines"]),
            generator.SELECTION_COUNT,
        )


if __name__ == "__main__":
    unittest.main()
