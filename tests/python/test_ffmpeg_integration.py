from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import main

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None
FFPROBE_AVAILABLE = shutil.which("ffprobe") is not None


@unittest.skipUnless(
    FFMPEG_AVAILABLE and FFPROBE_AVAILABLE,
    "FFmpeg and ffprobe are required for the real audio integration test.",
)
class RealFfmpegIntegrationTests(unittest.TestCase):
    def create_tone(
        self,
        output_path: Path,
        *,
        frequency: int,
        sample_rate: int,
        channels: int,
        metadata: dict[str, str] | None = None,
    ) -> None:
        command = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate={sample_rate}",
            "-t",
            "0.1",
            "-ac",
            str(channels),
            "-codec:a",
            "libmp3lame",
        ]
        for key, value in (metadata or {}).items():
            command.extend(["-metadata", f"{key}={value}"])
        command.append(str(output_path))
        subprocess.run(command, check=True)

    def test_mixed_inputs_are_normalized_and_titled(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            work_dir = Path(directory)
            first = work_dir / "first.mp3"
            second = work_dir / "second.mp3"
            output = work_dir / "merged.mp3"
            source_metadata = {
                "artist": "SOURCE_ARTIST_SENTINEL",
                "album": "SOURCE_ALBUM_SENTINEL",
                "comment": "SOURCE_COMMENT_SENTINEL",
            }
            self.create_tone(
                first,
                frequency=440,
                sample_rate=44_100,
                channels=2,
                metadata=source_metadata,
            )
            self.create_tone(second, frequency=660, sample_rate=48_000, channels=1)

            source_probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format_tags=artist,album,comment",
                    "-of",
                    "json",
                    str(first),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            source_tags = json.loads(source_probe.stdout)["format"]["tags"]
            self.assertEqual(source_tags["artist"], source_metadata["artist"])
            self.assertEqual(source_tags["album"], source_metadata["album"])
            self.assertEqual(source_tags["comment"], source_metadata["comment"])

            with (
                patch.object(main, "OUTPUT_SAMPLE_RATE", "44100"),
                patch.object(main, "OUTPUT_CHANNEL_LAYOUT", "stereo"),
                patch.object(main, "MP3_QUALITY", "0"),
            ):
                main.merge_mp3([first, second], output, "Integration title")

            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "stream=codec_name,sample_rate,channels:format_tags=title,artist,album,comment",
                    "-of",
                    "json",
                    str(output),
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            metadata = json.loads(probe.stdout)
            output_size = output.stat().st_size

        self.assertGreater(output_size, 0)
        self.assertEqual(metadata["streams"][0]["codec_name"], "mp3")
        self.assertEqual(metadata["streams"][0]["sample_rate"], "44100")
        self.assertEqual(metadata["streams"][0]["channels"], 2)
        self.assertEqual(metadata["format"]["tags"]["title"], "Integration title")
        output_metadata = json.dumps(metadata)
        for sentinel in source_metadata.values():
            self.assertNotIn(sentinel, output_metadata)


if __name__ == "__main__":
    unittest.main()
