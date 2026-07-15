from __future__ import annotations

import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import TypeAlias

from fastapi import HTTPException, UploadFile

UploadByteCounter: TypeAlias = dict[str, int]


def cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def validate_upload(file: UploadFile) -> None:
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()

    if not filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail=f"Only MP3 files are supported: {filename}")

    # Browsers do not agree on a single Content-Type for MP3 uploads.
    allowed_content_types = {"audio/mpeg", "audio/mp3", "application/octet-stream", ""}
    if content_type not in allowed_content_types:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported Content-Type for {filename}: {content_type}",
        )


def sanitize_download_name(name: str, fallback: str, extension: str) -> str:
    sanitized = re.sub(r'[\\/:*?"<>|\x00-\x1f\x7f]+', "_", name or "").strip().strip(".")
    value = sanitized or fallback
    if not value.lower().endswith(extension.lower()):
        value = f"{value}{extension}"
    return value


def title_from_download_name(name: str) -> str:
    title = re.sub(r"\.mp3$", "", name or "", flags=re.IGNORECASE).strip()
    return title or "Merged MP3"


async def save_uploads_to_directory(
    files: list[UploadFile],
    work_dir: Path,
    prefix: str,
    total_bytes: UploadByteCounter,
    *,
    max_total_bytes: int,
    chunk_size: int,
    validator: Callable[[UploadFile], None] = validate_upload,
) -> list[Path]:
    saved_paths: list[Path] = []

    for index, upload in enumerate(files):
        validator(upload)
        suffix = Path(upload.filename or "input.mp3").suffix.lower() or ".mp3"
        output_path = work_dir / f"{prefix}_{index:04d}{suffix}"
        file_bytes = 0

        with output_path.open("wb") as out:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                file_bytes += len(chunk)
                total_bytes["value"] += len(chunk)
                if total_bytes["value"] > max_total_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "Upload size exceeds the configured limit of "
                            f"{max_total_bytes} bytes."
                        ),
                    )
                out.write(chunk)

        if file_bytes == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Empty files are not supported: {upload.filename}",
            )
        saved_paths.append(output_path)

    return saved_paths
