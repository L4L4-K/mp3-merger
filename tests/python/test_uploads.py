from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import main
from tests.python.support import make_upload


class UploadValidationContractTests(unittest.TestCase):
    def assert_http_error(self, upload: object, status: int, detail: str) -> None:
        with self.assertRaises(HTTPException) as raised:
            main.validate_upload(upload)
        self.assertEqual(raised.exception.status_code, status)
        self.assertEqual(raised.exception.detail, detail)

    def test_allowed_content_types(self) -> None:
        for content_type in ("audio/mpeg", "audio/mp3", "application/octet-stream", None):
            with self.subTest(content_type=content_type):
                main.validate_upload(make_upload("track.MP3", content_type=content_type))

    def test_extension_is_required_even_for_audio_mime(self) -> None:
        self.assert_http_error(
            make_upload("track.bin", content_type="audio/mpeg"),
            400,
            "Only MP3 files are supported: track.bin",
        )

    def test_unsupported_content_type(self) -> None:
        self.assert_http_error(
            make_upload("track.mp3", content_type="text/plain"),
            400,
            "Unsupported Content-Type for track.mp3: text/plain",
        )


class FilenameContractTests(unittest.TestCase):
    def test_download_name_sanitization_and_extension(self) -> None:
        self.assertEqual(
            main.sanitize_download_name('  ../bad:name?.MP3  ', "fallback.mp3", ".mp3"),
            "_bad_name_.MP3",
        )
        self.assertEqual(main.sanitize_download_name("...", "fallback", ".zip"), "fallback.zip")
        self.assertEqual(main.sanitize_download_name("archive", "fallback.zip", ".zip"), "archive.zip")

    def test_title_from_download_name(self) -> None:
        self.assertEqual(main.title_from_download_name("Chapter 1.MP3"), "Chapter 1")
        self.assertEqual(main.title_from_download_name("  Chapter 1.MP3  "), "Chapter 1.MP3")
        self.assertEqual(main.title_from_download_name(".mp3"), "Merged MP3")


class SaveUploadsContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_validation_remains_patchable_through_main_facade(self) -> None:
        upload = make_upload("one.mp3", b"content")
        rejection = HTTPException(status_code=400, detail="rejected by facade")

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "validate_upload", side_effect=rejection) as validator:
                with self.assertRaises(HTTPException) as raised:
                    await main.save_uploads(
                        [upload],
                        Path(directory),
                        "input",
                        {"value": 0},
                    )

        self.assertIs(raised.exception, rejection)
        validator.assert_called_once_with(upload)

    async def test_saves_in_order_with_generated_names_and_updates_total(self) -> None:
        uploads = [
            make_upload("second.MP3", b"second"),
            make_upload("first.mp3", b"first"),
        ]
        counter = {"value": 5}

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "MAX_TOTAL_BYTES", 1_073_741_824):
                paths = await main.save_uploads(uploads, Path(directory), "source", counter)

            self.assertEqual([path.name for path in paths], ["source_0000.mp3", "source_0001.mp3"])
            self.assertEqual(paths[0].read_bytes(), b"second")
            self.assertEqual(paths[1].read_bytes(), b"first")
            self.assertEqual(counter["value"], 16)

    async def test_total_size_limit_is_inclusive(self) -> None:
        uploads = [make_upload("one.mp3", b"12"), make_upload("two.mp3", b"34")]
        counter = {"value": 0}

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "MAX_TOTAL_BYTES", 4), patch.object(main, "CHUNK_SIZE", 2):
                paths = await main.save_uploads(uploads, Path(directory), "input", counter)

        self.assertEqual(len(paths), 2)
        self.assertEqual(counter["value"], 4)

    async def test_total_size_limit_error_is_unchanged(self) -> None:
        uploads = [make_upload("one.mp3", b"12"), make_upload("two.mp3", b"345")]
        counter = {"value": 0}

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "MAX_TOTAL_BYTES", 4), patch.object(main, "CHUNK_SIZE", 2):
                with self.assertRaises(HTTPException) as raised:
                    await main.save_uploads(uploads, Path(directory), "input", counter)

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(
            raised.exception.detail,
            "Upload size exceeds the configured limit of 4 bytes.",
        )

    async def test_empty_file_error_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(HTTPException) as raised:
                await main.save_uploads(
                    [make_upload("empty.mp3", b"")],
                    Path(directory),
                    "input",
                    {"value": 0},
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Empty files are not supported: empty.mp3")


if __name__ == "__main__":
    unittest.main()
