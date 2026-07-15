from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"
DEFAULT_MAX_TOTAL_BYTES = 1024 * 1024 * 1024
DEFAULT_CHUNK_SIZE = 1024 * 1024


@dataclass(frozen=True, slots=True)
class Settings:
    max_files: int
    max_total_bytes: int
    mp3_quality: str
    output_sample_rate: str
    output_channel_layout: str
    chunk_size: int = DEFAULT_CHUNK_SIZE


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    values = os.environ if environ is None else environ
    return Settings(
        max_files=int(values.get("MAX_FILES", "100")),
        max_total_bytes=int(values.get("MAX_TOTAL_BYTES", str(DEFAULT_MAX_TOTAL_BYTES))),
        mp3_quality=values.get("MP3_QUALITY", "0"),
        output_sample_rate=values.get("OUTPUT_SAMPLE_RATE", "44100"),
        output_channel_layout=values.get("OUTPUT_CHANNEL_LAYOUT", "stereo"),
    )
