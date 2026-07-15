from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import HTTPException

from app import main


class FfmpegCommandContractTests(unittest.TestCase):
    def test_command_preserves_input_order_filters_and_metadata(self) -> None:
        with (
            patch.object(main, "OUTPUT_SAMPLE_RATE", "44100"),
            patch.object(main, "OUTPUT_CHANNEL_LAYOUT", "stereo"),
            patch.object(main, "MP3_QUALITY", "0"),
        ):
            command = main.build_ffmpeg_command(
                [Path("one.mp3"), Path("two.mp3")],
                Path("merged.mp3"),
                "Chapter One",
            )

        self.assertEqual(
            command,
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-y",
                "-i",
                "one.mp3",
                "-i",
                "two.mp3",
                "-filter_complex",
                "[0:a:0]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,"
                "asetpts=N/SR/TB[a0];"
                "[1:a:0]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,"
                "asetpts=N/SR/TB[a1];"
                "[a0][a1]concat=n=2:v=0:a=1[outa]",
                "-map",
                "[outa]",
                "-map_metadata",
                "-1",
                "-map_chapters",
                "-1",
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-q:a",
                "0",
                "-id3v2_version",
                "3",
                "-metadata",
                "title=Chapter One",
                "merged.mp3",
            ],
        )

    def test_blank_title_omits_metadata_argument(self) -> None:
        command = main.build_ffmpeg_command([Path("one.mp3")], Path("merged.mp3"), "  ")
        self.assertNotIn("-metadata", command)
        self.assertEqual(command[command.index("-map_metadata") + 1], "-1")
        self.assertEqual(command[command.index("-map_chapters") + 1], "-1")
        self.assertEqual(command[-1], "merged.mp3")

    def test_environment_backed_command_values_remain_patchable(self) -> None:
        with (
            patch.object(main, "OUTPUT_SAMPLE_RATE", "48000"),
            patch.object(main, "OUTPUT_CHANNEL_LAYOUT", "mono"),
            patch.object(main, "MP3_QUALITY", "5"),
        ):
            command = main.build_ffmpeg_command([Path("one.mp3")], Path("merged.mp3"))

        filter_graph = command[command.index("-filter_complex") + 1]
        self.assertIn("aresample=48000", filter_graph)
        self.assertIn("channel_layouts=mono", filter_graph)
        self.assertEqual(command[command.index("-q:a") + 1], "5")


class FfmpegExecutionContractTests(unittest.TestCase):
    def test_ensure_ffmpeg_translates_missing_binary(self) -> None:
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with self.assertRaises(HTTPException) as raised:
                main.ensure_ffmpeg()

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            "FFmpeg is not installed or is not on PATH.",
        )

    def test_successful_merge_checks_output_and_uses_one_hour_timeout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "merged.mp3"

            def run_success(command: list[str], **kwargs: object) -> SimpleNamespace:
                output_path.write_bytes(b"ID3")
                self.assertEqual(command[-1], str(output_path))
                self.assertEqual(kwargs["timeout"], 3600)
                return SimpleNamespace(returncode=0, stderr="", stdout="")

            with patch.object(main, "ensure_ffmpeg"), patch("subprocess.run", side_effect=run_success):
                main.merge_mp3([Path(directory) / "input.mp3"], output_path, "Title")

            self.assertEqual(output_path.read_bytes(), b"ID3")

    def test_timeout_error_is_unchanged(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "merged.mp3"
            with (
                patch.object(main, "ensure_ffmpeg"),
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired(["ffmpeg"], 3600)),
            ):
                with self.assertRaises(HTTPException) as raised:
                    main.merge_mp3([Path(directory) / "input.mp3"], output_path)

        self.assertEqual(raised.exception.status_code, 504)
        self.assertEqual(
            raised.exception.detail,
            "FFmpeg timed out while merging the files.",
        )

    def test_failure_returns_only_stderr_tail(self) -> None:
        stderr = "prefix" + ("x" * 3100)
        result = SimpleNamespace(returncode=1, stderr=stderr, stdout="")

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "ensure_ffmpeg"), patch("subprocess.run", return_value=result):
                with self.assertRaises(HTTPException) as raised:
                    main.merge_mp3(
                        [Path(directory) / "input.mp3"],
                        Path(directory) / "merged.mp3",
                    )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertTrue(
            str(raised.exception.detail).startswith(
                "FFmpeg failed to merge the files. Check that every input file is a valid MP3.\n"
            )
        )
        self.assertTrue(str(raised.exception.detail).endswith("x" * 3000))
        self.assertNotIn("prefix", str(raised.exception.detail))

    def test_missing_output_error_is_unchanged(self) -> None:
        result = SimpleNamespace(returncode=0, stderr="", stdout="")

        with tempfile.TemporaryDirectory() as directory:
            with patch.object(main, "ensure_ffmpeg"), patch("subprocess.run", return_value=result):
                with self.assertRaises(HTTPException) as raised:
                    main.merge_mp3(
                        [Path(directory) / "input.mp3"],
                        Path(directory) / "merged.mp3",
                    )

        self.assertEqual(raised.exception.status_code, 500)
        self.assertEqual(
            raised.exception.detail,
            "FFmpeg did not create a valid MP3 output.",
        )


if __name__ == "__main__":
    unittest.main()
