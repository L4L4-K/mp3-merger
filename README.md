# MP3 Batch Merger

MP3 Batch Merger is a local web app for turning many small MP3 files into clean, ordered chapter-style outputs. Drop files into batches, name the results, merge everything in order, and download one ZIP archive containing the finished MP3s.

It is designed for the repetitive audio cleanup work that is awkward to do by hand: organizing lessons, podcast segments, narration takes, audiobook sections, meeting recordings, or any folder of numbered clips that should become a smaller set of polished MP3 files.

## When It Helps

- You recorded a lesson in many short clips and want `Section1.mp3`, `Section2.mp3`, and so on.
- You have podcast or narration takes that need to be grouped into publishable parts.
- You split source audio by topic and now want a single MP3 per topic.
- You need to merge many batches at once without manually running FFmpeg commands.
- You want predictable filenames and a single ZIP download instead of many browser downloads.

## Highlights

- Build multiple independent batches in one browser session.
- Drag and drop or select MP3 files.
- Each new selection is sorted by filename before it is appended to the active batch.
- Reorder files manually with drag and drop or move buttons.
- Choose custom output names per batch.
- Write the same batch name into the MP3 ID3 title metadata.
- Do not copy artist, album, comment, or chapter metadata from source files.
- Generate sequential names from a starting value, such as `Section1.mp3`, `Section2.mp3`, and `Section3.mp3`.
- Set the ZIP archive filename before merging.
- See batch-by-batch progress while merging.
- Keep the interface locked while a merge is running so the job cannot be changed mid-process.
- Merge through FFmpeg at the highest configured MP3 VBR quality.

## Workflow

1. Add MP3 files to Batch 1.
2. Add more batches as needed.
3. Choose either per-batch names or generated sequential names.
4. Set the ZIP archive name.
5. Click **Merge Ready Batches**.
6. Download one ZIP containing the merged MP3 outputs.

Blank names are automatically restored to sensible defaults:

- ZIP archive: `mp3-batches.zip`
- Custom batch names: `Batch1.mp3`, `Batch2.mp3`, and so on
- Sequential name start: `Section1`

## Run With Docker

```bash
docker compose up --build
```

Open:

```text
http://localhost:8000
```

You can also run the image directly:

```bash
docker build -t mp3-merger .
docker run --rm -p 8000:8000 mp3-merger
```

## Run Without Docker

Install prerequisites:

- Python 3.12 or newer
- FFmpeg on `PATH`

Create a virtual environment and install the Python dependencies:

```bash
python -m venv .venv
```

Activate it with PowerShell on Windows:

```powershell
.venv\Scripts\Activate.ps1
```

Or activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

Then install dependencies:

```bash
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Start the server:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

If you use `uv`, you can start the app without manually creating a virtual environment:

```bash
uv run --python 3.12 --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Configuration

The Docker Compose file sets these environment variables. They can also be set before starting `uvicorn` in a non-Docker environment.

| Variable | Default | Description |
|---|---:|---|
| `MAX_FILES` | `100` | Maximum files per batch |
| `MAX_TOTAL_BYTES` | `1073741824` | Maximum total upload size per request. Default is 1 GiB |
| `MP3_QUALITY` | `0` | FFmpeg `libmp3lame` VBR quality. `0` is the highest quality |
| `OUTPUT_SAMPLE_RATE` | `44100` | Output sample rate |
| `OUTPUT_CHANNEL_LAYOUT` | `stereo` | Output channel layout, such as `stereo` or `mono` |

## Development Checks

After installing the Python dependencies, run the backend unit, contract, and integration tests with:

```bash
python -B -m unittest discover -s tests/python -t . -v
```

The real audio integration test runs when both FFmpeg and ffprobe are on `PATH`; otherwise that one test is skipped.

Frontend checks use Node.js 22 (the CI baseline) only for development validation. The app itself still runs directly in the browser, and the repository has no npm dependencies, so `npm install` is not required:

```bash
npm run check
npm test
```

An optional synthetic benchmark measures whether a blocking merge stalls the event loop. It does not invoke FFmpeg or measure audio throughput:

```bash
python -B -m benchmarks.event_loop_responsiveness
```

## Project Structure

```text
.
|-- benchmarks
|   `-- event_loop_responsiveness.py
|-- app
|   |-- __init__.py
|   |-- audio.py
|   |-- config.py
|   |-- main.py
|   |-- manifests.py
|   `-- uploads.py
|-- docs
|   |-- refactoring
|   |   `-- plan.md
|   `-- research
|       `-- 2026-07-15-technical-improvements.md
|-- static
|   |-- app.js
|   |-- css
|   |   |-- base.css
|   |   |-- batches.css
|   |   |-- files.css
|   |   |-- forms.css
|   |   |-- layout.css
|   |   |-- responsive.css
|   |   `-- tokens.css
|   |-- index.html
|   |-- js
|   |   |-- api.js
|   |   |-- dom.js
|   |   |-- jobs.js
|   |   |-- naming.js
|   |   |-- render.js
|   |   |-- state.js
|   |   |-- utils.js
|   |   `-- zip.js
|   `-- styles.css
|-- tests
|   |-- js
|   |   `-- frontend.test.js
|   `-- python
|       |-- test_audio.py
|       |-- test_configuration_and_manifest.py
|       |-- test_ffmpeg_integration.py
|       |-- test_routes.py
|       `-- test_uploads.py
|-- docker-compose.yml
|-- Dockerfile
|-- LICENSE
|-- package.json
|-- README.md
`-- requirements.txt
```

## Implementation Notes

MP3 files cannot be safely merged by concatenating bytes. The backend uses FFmpeg to normalize each input to the configured sample rate and channel layout, then merges the audio with the concat filter and re-encodes the output as MP3.

FFmpeg work runs outside the asynchronous server event loop so health and other lightweight requests remain responsive. A process-local gate keeps one merge active per event loop, matching the application's previous effective concurrency and avoiding an uncontrolled number of encoders. If a request task is cancelled while FFmpeg is running, cleanup waits for the worker to finish before removing its temporary files.

Output metadata is explicit: source metadata and chapters are not copied, and only the requested batch title is written. In the browser, ZIP CRC32 values are calculated from Blob streams so packaging does not retain a second full `Uint8Array` copy of every merged MP3.

## License

This project is released under the MIT License. See `LICENSE` for details.
