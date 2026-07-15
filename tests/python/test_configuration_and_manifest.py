from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from fastapi import HTTPException

from app import main
from app.config import load_settings


class ConfigurationContractTests(unittest.TestCase):
    def test_default_values(self) -> None:
        settings = load_settings({})

        self.assertEqual(settings.max_files, 100)
        self.assertEqual(settings.max_total_bytes, 1_073_741_824)
        self.assertEqual(settings.mp3_quality, "0")
        self.assertEqual(settings.output_sample_rate, "44100")
        self.assertEqual(settings.output_channel_layout, "stereo")
        self.assertEqual(settings.chunk_size, 1_048_576)

    def test_environment_overrides_are_loaded_at_import_time(self) -> None:
        environment = os.environ.copy()
        environment.update(
            {
                "MAX_FILES": "7",
                "MAX_TOTAL_BYTES": "12345",
                "MP3_QUALITY": "4",
                "OUTPUT_SAMPLE_RATE": "48000",
                "OUTPUT_CHANNEL_LAYOUT": "mono",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
        )
        command = (
            "import json; from app import main; "
            "print(json.dumps([main.MAX_FILES, main.MAX_TOTAL_BYTES, main.MP3_QUALITY, "
            "main.OUTPUT_SAMPLE_RATE, main.OUTPUT_CHANNEL_LAYOUT]))"
        )

        result = subprocess.run(
            [sys.executable, "-B", "-c", command],
            cwd=main.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=True,
        )

        self.assertEqual(json.loads(result.stdout), [7, 12345, "4", "48000", "mono"])

    def test_invalid_integer_environment_value_still_fails_import(self) -> None:
        environment = os.environ.copy()
        environment["MAX_FILES"] = "not-an-integer"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"

        result = subprocess.run(
            [sys.executable, "-B", "-c", "from app import main"],
            cwd=main.BASE_DIR,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ValueError", result.stderr)


class BatchManifestContractTests(unittest.TestCase):
    def assert_http_error(self, raw_manifest: object, status: int, detail: str) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.parse_batch_manifest(raw_manifest)
        self.assertEqual(raised.exception.status_code, status)
        self.assertEqual(raised.exception.detail, detail)

    def test_valid_manifest_preserves_order_and_normalizes_title(self) -> None:
        raw_manifest = json.dumps(
            [
                {"field": "first", "filename": "One.mp3", "title": "Title One", "ignored": True},
                {"field": "second", "filename": "Two.mp3", "title": 42},
            ]
        )

        self.assertEqual(
            main.parse_batch_manifest(raw_manifest),
            [
                {"field": "first", "filename": "One.mp3", "title": "Title One"},
                {"field": "second", "filename": "Two.mp3", "title": ""},
            ],
        )

    def test_missing_manifest(self) -> None:
        self.assert_http_error(None, 400, "Missing batch manifest.")

    def test_invalid_json(self) -> None:
        self.assert_http_error("{", 400, "Batch manifest is not valid JSON.")

    def test_empty_or_non_list_manifest(self) -> None:
        for value in ("[]", "{}", '"batch"'):
            with self.subTest(value=value):
                self.assert_http_error(value, 400, "At least one batch is required.")

    def test_non_object_entry(self) -> None:
        self.assert_http_error('["batch"]', 400, "Batch 1 is invalid.")

    def test_missing_field_name(self) -> None:
        self.assert_http_error(
            '[{"filename": "One.mp3"}]',
            400,
            "Batch 1 is missing a field name.",
        )

    def test_missing_output_filename(self) -> None:
        self.assert_http_error(
            '[{"field": "files", "filename": "  "}]',
            400,
            "Batch 1 is missing an output filename.",
        )


if __name__ == "__main__":
    unittest.main()
