# MP3 Merger

A local web app for building multiple ordered MP3 batches and merging each batch into a single MP3. Batch results are returned together in one ZIP archive.

## Features

- Drag and drop or select multiple MP3 files.
- Create and manage multiple batches.
- Run all ready batches in one request.
- Download a single ZIP that contains one merged MP3 per batch.
- Choose custom output names per batch.
- Generate sequential output names from a starting name, such as `Section1.mp3`, `Section2.mp3`, and `Section3.mp3`.
- Sort each newly added selection by filename before appending it to the active batch.
- Reorder files with drag and drop or the move buttons.
- Merge audio through FFmpeg with normalized sample rate and channel layout.

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
.venv\Scripts\activate
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

If you use `uv`, the same app can be started without manually creating a virtual environment:

```bash
uv run --python 3.12 --with-requirements requirements.txt uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Configuration

The Docker Compose file sets these environment variables. They can also be set in any non-Docker environment before starting `uvicorn`.

| Variable | Default | Description |
|---|---:|---|
| `MAX_FILES` | `100` | Maximum files per batch |
| `MAX_TOTAL_BYTES` | `1073741824` | Maximum total upload size per request. Default is 1 GiB |
| `MP3_QUALITY` | `2` | FFmpeg `libmp3lame` VBR quality. Lower values are higher quality |
| `OUTPUT_SAMPLE_RATE` | `44100` | Output sample rate |
| `OUTPUT_CHANNEL_LAYOUT` | `stereo` | Output channel layout, such as `stereo` or `mono` |

## Project Structure

```text
.
|-- app
|   `-- main.py
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
|   |   |-- naming.js
|   |   |-- render.js
|   |   |-- state.js
|   |   `-- utils.js
|   `-- styles.css
|-- docker-compose.yml
|-- Dockerfile
|-- README.md
`-- requirements.txt
```

## Implementation Notes

MP3 files cannot be safely merged by concatenating bytes. The backend uses FFmpeg to normalize each input to the configured sample rate and channel layout, then merges the audio with the concat filter and re-encodes the output as MP3.
