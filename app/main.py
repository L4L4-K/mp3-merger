from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Annotated

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

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
        raise HTTPException(status_code=500, detail="FFmpeg が見つかりません。") from None


def validate_upload(file: UploadFile) -> None:
    filename = file.filename or ""
    content_type = (file.content_type or "").lower()

    if not filename.lower().endswith(".mp3"):
        raise HTTPException(status_code=400, detail=f"MP3 以外のファイルが含まれています: {filename}")

    # Some browsers send audio/mpeg, others can send application/octet-stream.
    allowed_content_types = {"audio/mpeg", "audio/mp3", "application/octet-stream", ""}
    if content_type not in allowed_content_types:
        raise HTTPException(
            status_code=400,
            detail=f"MP3 として扱えない Content-Type です: {filename} ({content_type})",
        )


async def save_uploads(files: list[UploadFile], work_dir: Path) -> list[Path]:
    saved_paths: list[Path] = []
    total_bytes = 0

    for index, upload in enumerate(files):
        validate_upload(upload)
        suffix = Path(upload.filename or "input.mp3").suffix.lower() or ".mp3"
        output_path = work_dir / f"input_{index:04d}{suffix}"
        file_bytes = 0

        with output_path.open("wb") as out:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                file_bytes += len(chunk)
                total_bytes += len(chunk)
                if total_bytes > MAX_TOTAL_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"アップロード合計サイズが上限を超えています: {MAX_TOTAL_BYTES} bytes",
                    )
                out.write(chunk)

        if file_bytes == 0:
            raise HTTPException(status_code=400, detail=f"空のファイルです: {upload.filename}")
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
        raise HTTPException(status_code=504, detail="変換がタイムアウトしました。") from None

    if result.returncode != 0:
        stderr_tail = result.stderr[-3000:] if result.stderr else ""
        raise HTTPException(
            status_code=400,
            detail="FFmpeg による結合に失敗しました。入力ファイルが壊れていないか確認してください。\n" + stderr_tail,
        )

    if not output_path.exists() or output_path.stat().st_size == 0:
        raise HTTPException(status_code=500, detail="出力 MP3 を作成できませんでした。")


@app.get("/", response_class=HTMLResponse)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.post("/api/merge")
async def merge_endpoint(
    background_tasks: BackgroundTasks,
    files: Annotated[list[UploadFile], File(description="Order-sensitive MP3 files")],
) -> FileResponse:
    if len(files) < 2:
        raise HTTPException(status_code=400, detail="2 つ以上の MP3 ファイルを選択してください。")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=413, detail=f"ファイル数が上限を超えています: {MAX_FILES}")

    tmp_dir = tempfile.mkdtemp(prefix="mp3_merge_")
    work_dir = Path(tmp_dir)

    try:
        input_paths = await save_uploads(files, work_dir)
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


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
