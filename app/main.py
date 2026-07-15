from __future__ import annotations

import asyncio
import logging
import tempfile
import zipfile
from pathlib import Path
from typing import Annotated, Any
from weakref import WeakKeyDictionary

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile as StarletteUploadFile

from app.audio import (
    AudioEncodingSettings,
    build_ffmpeg_command as build_configured_ffmpeg_command,
)
from app.audio import ensure_ffmpeg as check_ffmpeg
from app.audio import execute_ffmpeg
from app.config import BASE_DIR, STATIC_DIR, load_settings
from app.manifests import parse_batch_manifest as parse_manifest
from app.uploads import cleanup_dir as remove_work_dir
from app.uploads import sanitize_download_name as sanitize_name
from app.uploads import save_uploads_to_directory
from app.uploads import title_from_download_name as title_from_name
from app.uploads import validate_upload as validate_mp3_upload

settings = load_settings()
logger = logging.getLogger(__name__)
MAX_FILES = settings.max_files
MAX_TOTAL_BYTES = settings.max_total_bytes
MP3_QUALITY = settings.mp3_quality
OUTPUT_SAMPLE_RATE = settings.output_sample_rate
OUTPUT_CHANNEL_LAYOUT = settings.output_channel_layout
CHUNK_SIZE = settings.chunk_size

app = FastAPI(title="MP3 Merger")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_merge_limiters: WeakKeyDictionary[
    asyncio.AbstractEventLoop, asyncio.Semaphore
] = WeakKeyDictionary()


def cleanup_dir(path: str) -> None:
    remove_work_dir(path)


def ensure_ffmpeg() -> None:
    check_ffmpeg()


def validate_upload(file: UploadFile) -> None:
    validate_mp3_upload(file)


def sanitize_download_name(name: str, fallback: str, extension: str) -> str:
    return sanitize_name(name, fallback, extension)


def title_from_download_name(name: str) -> str:
    return title_from_name(name)


async def save_uploads(
    files: list[UploadFile],
    work_dir: Path,
    prefix: str,
    total_bytes: dict[str, int],
) -> list[Path]:
    return await save_uploads_to_directory(
        files,
        work_dir,
        prefix,
        total_bytes,
        max_total_bytes=MAX_TOTAL_BYTES,
        chunk_size=CHUNK_SIZE,
        validator=validate_upload,
    )


def build_ffmpeg_command(
    input_paths: list[Path],
    output_path: Path,
    title: str | None = None,
) -> list[str]:
    return build_configured_ffmpeg_command(
        input_paths,
        output_path,
        title,
        AudioEncodingSettings(
            mp3_quality=MP3_QUALITY,
            output_sample_rate=OUTPUT_SAMPLE_RATE,
            output_channel_layout=OUTPUT_CHANNEL_LAYOUT,
        ),
    )


def merge_mp3(
    input_paths: list[Path],
    output_path: Path,
    title: str | None = None,
) -> None:
    ensure_ffmpeg()
    command = build_ffmpeg_command(input_paths, output_path, title)
    execute_ffmpeg(command, output_path)


def _get_merge_limiter() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    limiter = _merge_limiters.get(loop)
    if limiter is None:
        limiter = asyncio.Semaphore(1)
        _merge_limiters[loop] = limiter
    return limiter


async def _run_merge_mp3(
    input_paths: list[Path],
    output_path: Path,
    title: str | None,
) -> None:
    async with _get_merge_limiter():
        worker = asyncio.create_task(
            run_in_threadpool(merge_mp3, input_paths, output_path, title),
            name="mp3-merge-thread",
        )
        cancellation: asyncio.CancelledError | None = None
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError as exc:
                if cancellation is None:
                    cancellation = exc
            except BaseException:
                if not worker.done():
                    raise
                break

        if cancellation is not None:
            try:
                worker.result()
            except BaseException:
                logger.debug(
                    "MP3 merge worker failed after request cancellation.",
                    exc_info=True,
                )
            raise cancellation

        worker.result()


def parse_batch_manifest(raw_manifest: Any) -> list[dict[str, str]]:
    return [dict(entry) for entry in parse_manifest(raw_manifest)]


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/merge")
async def merge_endpoint(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="Order-sensitive MP3 files")],
    title: Annotated[str | None, Form()] = None,
) -> FileResponse:
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="Select at least two MP3 files.")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"Too many files. The limit is {MAX_FILES}.")

    tmp_dir = tempfile.mkdtemp(prefix="mp3_merge_")
    work_dir = Path(tmp_dir)
    response_ready = False

    try:
        input_paths = await save_uploads(files, work_dir, "input", {"value": 0})
        output_path = work_dir / "merged.mp3"
        await _run_merge_mp3(input_paths, output_path, title)
        background_tasks.add_task(cleanup_dir, tmp_dir)
        response = FileResponse(
            output_path,
            media_type="audio/mpeg",
            filename="merged.mp3",
            background=background_tasks,
        )
        response_ready = True
        return response
    finally:
        if not response_ready:
            cleanup_dir(tmp_dir)


@app.post("/api/merge-batches")
async def merge_batches_endpoint(
    background_tasks: BackgroundTasks,
    request: Request,
) -> FileResponse:
    form = await request.form()
    batches = parse_batch_manifest(form.get("manifest"))
    archive_name = sanitize_download_name(
        str(form.get("archive_name") or ""),
        "mp3-batches.zip",
        ".zip",
    )

    tmp_dir = tempfile.mkdtemp(prefix="mp3_merge_batches_")
    work_dir = Path(tmp_dir)
    output_dir = work_dir / "outputs"
    total_bytes = {"value": 0}
    output_names: set[str] = set()
    merged_outputs: list[Path] = []
    response_ready = False

    try:
        output_dir.mkdir()
        for index, batch in enumerate(batches, start=1):
            files = form.getlist(batch["field"])
            upload_files = [file for file in files if isinstance(file, StarletteUploadFile)]

            if len(upload_files) < 2:
                raise HTTPException(
                    status_code=400,
                    detail=f"Batch {index} must contain at least two MP3 files.",
                )
            if len(upload_files) > MAX_FILES:
                raise HTTPException(
                    status_code=413,
                    detail=f"Batch {index} exceeds the file limit of {MAX_FILES}.",
                )

            output_name = sanitize_download_name(
                batch["filename"],
                f"Batch{index}.mp3",
                ".mp3",
            )
            metadata_title = batch["title"].strip() or title_from_download_name(output_name)
            output_key = output_name.lower()
            if output_key in output_names:
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate output filename: {output_name}",
                )
            output_names.add(output_key)

            batch_dir = work_dir / f"batch_{index:04d}"
            batch_dir.mkdir()
            input_paths = await save_uploads(upload_files, batch_dir, "input", total_bytes)
            output_path = output_dir / output_name
            await _run_merge_mp3(input_paths, output_path, metadata_title)
            merged_outputs.append(output_path)

        zip_path = work_dir / archive_name
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for output_path in merged_outputs:
                archive.write(output_path, arcname=output_path.name)
        background_tasks.add_task(cleanup_dir, tmp_dir)
        response = FileResponse(
            zip_path,
            media_type="application/zip",
            filename=archive_name,
            background=background_tasks,
        )
        response_ready = True
        return response
    finally:
        if not response_ready:
            cleanup_dir(tmp_dir)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
