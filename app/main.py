from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import UploadFile as StarletteUploadFile

BASE_DIR = Path(__file__).resolve().parent.parent
STATIC_DIR = BASE_DIR / "static"

MAX_FILES = int(os.getenv("MAX_FILES", "100"))
MAX_TOTAL_BYTES = int(os.getenv("MAX_TOTAL_BYTES", str(1024 * 1024 * 1024)))
MP3_QUALITY = os.getenv("MP3_QUALITY", "2")
OUTPUT_SAMPLE_RATE = os.getenv("OUTPUT_SAMPLE_RATE", "44100")
OUTPUT_CHANNEL_LAYOUT = os.getenv("OUTPUT_CHANNEL_LAYOUT", "stereo")
CHUNK_SIZE = 1024 * 1024

app = FastAPI(title="MP3 Merger")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def cleanup_dir(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)


def ensure_ffmpeg() -> None:
    try:
        subprocess.run(
            ["ffmpeg", "-version"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise HTTPException(status_code=500, detail="FFmpeg is not installed or is not on PATH.") from None


def validate_upload(file: UploadFile) -> None:
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()

    if not filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail=f"Only MP3 files are supported: {filename}")

    # Some browsers send audio/mpeg, others can send application/octet-stream.
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


async def save_uploads(
    files: list[UploadFile],
    work_dir: Path,
    prefix: str,
    total_bytes: dict[str, int],
) -> list[Path]:
    saved_paths: list[Path] = []

    for index, upload in enumerate(files):
        validate_upload(upload)
        suffix = Path(upload.filename or "input.mp3").suffix.lower() or ".mp3"
        output_path = work_dir / f"{prefix}_{index:04d}{suffix}"
        file_bytes = 0

        with output_path.open("wb") as out:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                file_bytes += len(chunk)
                total_bytes["value"] += len(chunk)
                if total_bytes["value"] > MAX_TOTAL_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"Upload size exceeds the configured limit of {MAX_TOTAL_BYTES} bytes.",
                    )
                out.write(chunk)

        if file_bytes == 0:
            raise HTTPException(status_code=400, detail=f"Empty files are not supported: {upload.filename}")
        saved_paths.append(output_path)

    return saved_paths


def build_ffmpeg_command(input_paths: list[Path], output_path: Path) -> list[str]:
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
            f"aresample={OUTPUT_SAMPLE_RATE},"
            f"aformat=sample_fmts=s16:channel_layouts={OUTPUT_CHANNEL_LAYOUT},"
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
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            MP3_QUALITY,
            "-id3v2_version",
            "3",
            str(output_path),
        ]
    )
    return command


def merge_mp3(input_paths: list[Path], output_path: Path) -> None:
    ensure_ffmpeg()
    command = build_ffmpeg_command(input_paths, output_path)

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
        raise HTTPException(status_code=504, detail="FFmpeg timed out while merging the files.") from None

    if result.returncode != 0:
        stderr_tail = result.stderr[-3000:] if result.stderr else ""
        raise HTTPException(
            status_code=400,
            detail="FFmpeg failed to merge the files. Check that every input file is a valid MP3.\n" + stderr_tail,
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="FFmpeg did not create a valid MP3 output.")


def parse_batch_manifest(raw_manifest: Any) -> list[dict[str, str]]:
    if not isinstance(raw_manifest, str):
        raise HTTPException(status_code=400, detail="Missing batch manifest.")

    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Batch manifest is not valid JSON.") from None

    if not isinstance(manifest, list) or not manifest:
        raise HTTPException(status_code=400, detail="At least one batch is required.")

    parsed: list[dict[str, str]] = []
    for index, entry in enumerate(manifest, start=1):
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"Batch {index} is invalid.")
        field = entry.get("field")
        filename = entry.get("filename")
        if not isinstance(field, str) or not field:
            raise HTTPException(status_code=400, detail=f"Batch {index} is missing a field name.")
        if not isinstance(filename, str) or not filename.strip():
            raise HTTPException(status_code=400, detail=f"Batch {index} is missing an output filename.")
        parsed.append({"field": field, "filename": filename})

    return parsed


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/merge")
async def merge_endpoint(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="Order-sensitive MP3 files")],
) -> FileResponse:
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Select at least two MP3 files.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files. The limit is {MAX_FILES}.")

    tmp_dir = tempfile.mkdtemp(prefix="mp3_merge_")
    work_dir = Path(tmp_dir)

    try:
        input_paths = await save_uploads(files, work_dir, "input", {"value": 0})
        output_path = work_dir / "merged.mp3"
        merge_mp3(input_paths, output_path)
    except Exception:
        cleanup_dir(tmp_dir)
        raise

    background_tasks.add_task(cleanup_dir, tmp_dir)
    return FileResponse(
        output_path,
        media_type="audio/mpeg",
        filename="merged.mp3",
        background=background_tasks,
    )


@app.post("/api/merge-batches")
async def merge_batches_endpoint(background_tasks: BackgroundTasks, request: Request) -> FileResponse:
    form = await request.form()
    batches = parse_batch_manifest(form.get("manifest"))
    archive_name = sanitize_download_name(str(form.get("archive_name") or ""), "mp3-batches.zip", ".zip")

    tmp_dir = tempfile.mkdtemp(prefix="mp3_merge_batches_")
    work_dir = Path(tmp_dir)
    output_dir = work_dir / "outputs"
    output_dir.mkdir()
    total_bytes = {"value": 0}
    output_names: set[str] = set()
    merged_outputs: list[Path] = []

    try:
        for index, batch in enumerate(batches, start=1):
            files = form.getlist(batch["field"])
            upload_files = [file for file in files if isinstance(file, StarletteUploadFile)]

            if len(upload_files) < 2:
                raise HTTPException(status_code=400, detail=f"Batch {index} must contain at least two MP3 files.")
            if len(upload_files) > MAX_FILES:
                raise HTTPException(status_code=413, detail=f"Batch {index} exceeds the file limit of {MAX_FILES}.")

            output_name = sanitize_download_name(batch["filename"], f"Batch{index}.mp3", ".mp3")
            output_key = output_name.lower()
            if output_key in output_names:
                raise HTTPException(status_code=400, detail=f"Duplicate output filename: {output_name}")
            output_names.add(output_key)

            batch_dir = work_dir / f"batch_{index:04d}"
            batch_dir.mkdir()
            input_paths = await save_uploads(upload_files, batch_dir, "input", total_bytes)
            output_path = output_dir / output_name
            merge_mp3(input_paths, output_path)
            merged_outputs.append(output_path)

        zip_path = work_dir / archive_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for output_path in merged_outputs:
                archive.write(output_path, arcname=output_path.name)
    except Exception:
        cleanup_dir(tmp_dir)
        raise

    background_tasks.add_task(cleanup_dir, tmp_dir)
    return FileResponse(
        zip_path,
        media_type="application/zip",
        filename=archive_name,
        background=background_tasks,
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
