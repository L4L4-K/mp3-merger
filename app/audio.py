from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException


@dataclass(frozen=True, slots=True)
class AudioEncodingSettings:
    mp3_quality: str
    output_sample_rate: str
    output_channel_layout: str


def ensure_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise HTTPException(
            status_code=500,
            detail="FFmpeg is not installed or is not on PATH.",
        ) from None


def build_ffmpeg_command(
    input_paths: list[Path],
    output_path: Path,
    title: str | None,
    settings: AudioEncodingSettings,
) -> list[str]:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-y"]
    for path in input_paths:
        command.extend(["-i", str(path)])

    normalized_labels = []
    filter_parts = []
    for index in range(len(input_paths)):
        label = f"a{index}"
        normalized_labels.append(f"[{label}]")
        filter_parts.append(
            f"[{index}:a:0]"
            f"aresample={settings.output_sample_rate},"
            f"aformat=sample_fmts=s16:channel_layouts={settings.output_channel_layout},"
            f"asetpts=N/SR/TB"
            f"[{label}]"
        )

    concat_inputs = "".join(normalized_labels)
    filter_parts.append(f"{concat_inputs}concat=n={len(input_paths)}:v=0:a=1[outa]")
    filter_complex = ";".join(filter_parts)

    command.extend(
        [
            "-filter_complex",
            filter_complex,
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
            settings.mp3_quality,
            "-id3v2_version",
            "3",
        ]
    )
    metadata_title = (title or "").strip()
    if metadata_title:
        command.extend(["-metadata", f"title={metadata_title}"])

    command.append(str(output_path))
    return command


def execute_ffmpeg(command: list[str], output_path: Path) -> None:
    try:
        result = subprocess.run(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
            timeout=60 * 60,
        )
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail="FFmpeg timed out while merging the files.",
        ) from None

    if result.returncode != 0:
        stderr_tail = result.stderr[-3000:] if result.stderr else ""
        raise HTTPException(
            status_code=400,
            detail=(
                "FFmpeg failed to merge the files. "
                "Check that every input file is a valid MP3.\n"
                + stderr_tail
            ),
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise HTTPException(
            status_code=500,
            detail="FFmpeg did not create a valid MP3 output.",
        )
