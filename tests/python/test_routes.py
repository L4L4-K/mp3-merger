from __future__ import annotations

import asyncio
import inspect
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import FileResponse

from app import main
from tests.python.support import (
    FormStub,
    RequestStub,
    asgi_request,
    encode_multipart_file,
    make_upload,
)


class RouteContractTests(unittest.TestCase):
    def test_main_module_keeps_compatibility_facade_signatures(self) -> None:
        expected_parameters = {
            "cleanup_dir": ["path"],
            "ensure_ffmpeg": [],
            "validate_upload": ["file"],
            "sanitize_download_name": ["name", "fallback", "extension"],
            "title_from_download_name": ["name"],
            "save_uploads": ["files", "work_dir", "prefix", "total_bytes"],
            "build_ffmpeg_command": ["input_paths", "output_path", "title"],
            "merge_mp3": ["input_paths", "output_path", "title"],
            "parse_batch_manifest": ["raw_manifest"],
            "index": [],
            "merge_endpoint": ["background_tasks", "files", "title"],
            "merge_batches_endpoint": ["background_tasks", "request"],
            "health": [],
        }

        for name, parameter_names in expected_parameters.items():
            with self.subTest(name=name):
                function = getattr(main, name)
                self.assertEqual(list(inspect.signature(function).parameters), parameter_names)

    def test_registered_paths_and_methods(self) -> None:
        self.assertEqual(
            [route.path for route in main.app.routes],
            [
                "/openapi.json",
                "/docs",
                "/docs/oauth2-redirect",
                "/redoc",
                "/static",
                "/",
                "/api/merge",
                "/api/merge-batches",
                "/health",
            ],
        )
        methods = {
            route.path: route.methods
            for route in main.app.routes
            if getattr(route, "methods", None) is not None
        }
        self.assertEqual(methods["/"], {"GET"})
        self.assertEqual(methods["/api/merge"], {"POST"})
        self.assertEqual(methods["/api/merge-batches"], {"POST"})
        self.assertEqual(methods["/health"], {"GET"})

    def test_openapi_keeps_both_merge_paths(self) -> None:
        paths = main.app.openapi()["paths"]
        self.assertEqual(set(paths), {"/", "/api/merge", "/api/merge-batches", "/health"})
        self.assertIn("post", paths["/api/merge"])
        self.assertIn("post", paths["/api/merge-batches"])

    def test_index_and_health_contracts(self) -> None:
        response = main.index()
        self.assertIsInstance(response, FileResponse)
        self.assertEqual(Path(response.path), main.STATIC_DIR / "index.html")
        self.assertEqual(main.health(), {"status": "ok"})


class HttpContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_is_json_over_asgi(self) -> None:
        response = await asgi_request(main.app, "GET", "/health")

        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(json.loads(response.body), {"status": "ok"})

    async def test_index_is_html_over_asgi(self) -> None:
        response = await asgi_request(main.app, "GET", "/")

        self.assertEqual(response.status, 200)
        self.assertTrue(response.headers["content-type"].startswith("text/html"))
        self.assertEqual(response.body, (main.STATIC_DIR / "index.html").read_bytes())

    async def test_single_file_merge_error_keeps_http_json_contract(self) -> None:
        body, boundary = encode_multipart_file("files", "one.mp3", b"content")
        response = await asgi_request(
            main.app,
            "POST",
            "/api/merge",
            body=body,
            headers={
                "content-type": f"multipart/form-data; boundary={boundary}",
                "content-length": str(len(body)),
            },
        )

        self.assertEqual(response.status, 400)
        self.assertEqual(response.headers["content-type"], "application/json")
        self.assertEqual(json.loads(response.body), {"detail": "Select at least two MP3 files."})


class MergeEndpointContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_file_count_errors_are_unchanged(self) -> None:
        with self.assertRaises(HTTPException) as too_few:
            await main.merge_endpoint(BackgroundTasks(), [])
        self.assertEqual(too_few.exception.status_code, 400)
        self.assertEqual(too_few.exception.detail, "Select at least two MP3 files.")

        with patch.object(main, "MAX_FILES", 2):
            with self.assertRaises(HTTPException) as too_many:
                await main.merge_endpoint(BackgroundTasks(), [object(), object(), object()])
        self.assertEqual(too_many.exception.status_code, 413)
        self.assertEqual(too_many.exception.detail, "Too many files. The limit is 2.")

    async def test_success_response_and_cleanup_contract(self) -> None:
        uploads = [make_upload("one.mp3"), make_upload("two.mp3")]
        captured: dict[str, object] = {}

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            captured.update(files=files, work_dir=work_dir, prefix=prefix, total_bytes=total_bytes)
            return [work_dir / "input_0000.mp3", work_dir / "input_0001.mp3"]

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            captured.update(input_paths=input_paths, title=title)
            output_path.write_bytes(b"ID3")

        with patch.object(main, "MAX_FILES", 100), patch.object(
            main, "save_uploads", side_effect=save_stub
        ), patch.object(main, "merge_mp3", side_effect=merge_stub):
            response = await main.merge_endpoint(BackgroundTasks(), uploads, "Chapter")

        work_dir = captured["work_dir"]
        self.assertIsInstance(work_dir, Path)
        self.assertTrue(work_dir.exists())
        self.assertEqual(captured["prefix"], "input")
        self.assertEqual(captured["total_bytes"], {"value": 0})
        self.assertEqual(captured["title"], "Chapter")
        self.assertEqual(response.media_type, "audio/mpeg")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="merged.mp3"',
        )
        self.assertTrue(Path(response.path).is_file())

        self.assertIsNotNone(response.background)
        await response.background()
        self.assertFalse(work_dir.exists())

    async def test_processing_error_cleans_workspace_and_propagates(self) -> None:
        captured: dict[str, Path] = {}

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            captured["work_dir"] = work_dir
            return [work_dir / "one.mp3", work_dir / "two.mp3"]

        with patch.object(main, "MAX_FILES", 100), patch.object(
            main, "save_uploads", side_effect=save_stub
        ), patch.object(main, "merge_mp3", side_effect=RuntimeError("processing failed")):
            with self.assertRaisesRegex(RuntimeError, "processing failed"):
                await main.merge_endpoint(
                    BackgroundTasks(),
                    [make_upload("one.mp3"), make_upload("two.mp3")],
                )

        self.assertFalse(captured["work_dir"].exists())

    async def test_blocking_merge_keeps_event_loop_responsive(self) -> None:
        merge_started = threading.Event()
        health_done = threading.Event()
        merge_observed_health = False
        merge_thread_id: int | None = None
        event_loop_thread_id = threading.get_ident()

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            return [work_dir / "one.mp3", work_dir / "two.mp3"]

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            nonlocal merge_observed_health, merge_thread_id
            merge_thread_id = threading.get_ident()
            merge_started.set()
            merge_observed_health = health_done.wait(timeout=1)
            output_path.write_bytes(b"ID3")

        async def health_probe() -> object:
            while not merge_started.is_set():
                await asyncio.sleep(0)
            response = await asgi_request(main.app, "GET", "/health")
            health_done.set()
            return response

        probe_task = asyncio.create_task(health_probe())
        try:
            with (
                patch.object(main, "MAX_FILES", 100),
                patch.object(main, "save_uploads", side_effect=save_stub),
                patch.object(main, "merge_mp3", side_effect=merge_stub),
            ):
                response = await main.merge_endpoint(
                    BackgroundTasks(),
                    [make_upload("one.mp3"), make_upload("two.mp3")],
                )
            health_response = await probe_task
        finally:
            health_done.set()

        self.assertTrue(merge_observed_health)
        self.assertNotEqual(merge_thread_id, event_loop_thread_id)
        self.assertEqual(health_response.status, 200)
        self.assertIsNotNone(response.background)
        await response.background()

    async def test_upload_cancellation_cleans_workspace_and_propagates(self) -> None:
        save_started = asyncio.Event()
        keep_saving = asyncio.Event()
        captured: dict[str, Path] = {}

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            captured["work_dir"] = work_dir
            save_started.set()
            await keep_saving.wait()
            return []

        with patch.object(main, "MAX_FILES", 100), patch.object(
            main, "save_uploads", side_effect=save_stub
        ):
            task = asyncio.create_task(
                main.merge_endpoint(
                    BackgroundTasks(),
                    [make_upload("one.mp3"), make_upload("two.mp3")],
                )
            )
            await save_started.wait()
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertFalse(captured["work_dir"].exists())

    async def test_merge_cancellation_waits_for_worker_before_cleanup(self) -> None:
        merge_started = threading.Event()
        release_merge = threading.Event()
        merge_finished = threading.Event()
        events: list[str] = []
        captured: dict[str, Path] = {}
        cleanup_calls = 0
        original_cleanup = main.cleanup_dir

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            captured["work_dir"] = work_dir
            return [work_dir / "one.mp3", work_dir / "two.mp3"]

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            events.append("merge-start")
            merge_started.set()
            release_merge.wait()
            output_path.write_bytes(b"ID3")
            merge_finished.set()
            events.append("merge-finish")

        def cleanup_spy(path: str) -> None:
            nonlocal cleanup_calls
            cleanup_calls += 1
            self.assertTrue(merge_finished.is_set())
            events.append("cleanup")
            original_cleanup(path)

        with (
            patch.object(main, "MAX_FILES", 100),
            patch.object(main, "save_uploads", side_effect=save_stub),
            patch.object(main, "merge_mp3", side_effect=merge_stub),
            patch.object(main, "cleanup_dir", side_effect=cleanup_spy),
        ):
            task = asyncio.create_task(
                main.merge_endpoint(
                    BackgroundTasks(),
                    [make_upload("one.mp3"), make_upload("two.mp3")],
                )
            )
            try:
                self.assertTrue(await asyncio.to_thread(merge_started.wait, 1))
                task.cancel()
                await asyncio.sleep(0)
                self.assertFalse(task.done())
            finally:
                release_merge.set()

            with self.assertRaises(asyncio.CancelledError):
                await task

        self.assertEqual(events, ["merge-start", "merge-finish", "cleanup"])
        self.assertEqual(cleanup_calls, 1)
        self.assertFalse(captured["work_dir"].exists())

    async def test_merge_work_is_limited_to_one_job_per_event_loop(self) -> None:
        first_started = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        call_count = 0
        call_count_lock = threading.Lock()

        async def save_stub(
            files: object,
            work_dir: Path,
            prefix: str,
            total_bytes: dict[str, int],
        ) -> list[Path]:
            return [work_dir / "one.mp3", work_dir / "two.mp3"]

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            nonlocal call_count
            with call_count_lock:
                call_count += 1
                current_call = call_count
            if current_call == 1:
                first_started.set()
                release_first.wait()
            else:
                second_started.set()
            output_path.write_bytes(b"ID3")

        with (
            patch.object(main, "MAX_FILES", 100),
            patch.object(main, "save_uploads", side_effect=save_stub),
            patch.object(main, "merge_mp3", side_effect=merge_stub),
        ):
            first_task = asyncio.create_task(
                main.merge_endpoint(BackgroundTasks(), [object(), object()], "One")
            )
            self.assertTrue(await asyncio.to_thread(first_started.wait, 1))
            second_task = asyncio.create_task(
                main.merge_endpoint(BackgroundTasks(), [object(), object()], "Two")
            )
            await asyncio.sleep(0)
            self.assertFalse(second_started.is_set())
            release_first.set()
            first_response, second_response = await asyncio.gather(first_task, second_task)

        self.assertTrue(second_started.is_set())
        for response in (first_response, second_response):
            self.assertIsNotNone(response.background)
            await response.background()


class MergeBatchesEndpointContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_batch_file_count_errors_and_cleanup_are_unchanged(self) -> None:
        manifest = json.dumps([{"field": "files", "filename": "One.mp3"}])
        cases = [
            (
                [make_upload("one.mp3")],
                100,
                400,
                "Batch 1 must contain at least two MP3 files.",
            ),
            (
                [make_upload("one.mp3"), make_upload("two.mp3"), make_upload("three.mp3")],
                2,
                413,
                "Batch 1 exceeds the file limit of 2.",
            ),
        ]

        for files, max_files, status, detail in cases:
            with self.subTest(status=status):
                form = FormStub(
                    {"manifest": manifest, "archive_name": "archive.zip"},
                    {"files": files},
                )
                with tempfile.TemporaryDirectory() as parent:
                    work_dir = Path(tempfile.mkdtemp(dir=parent))
                    with patch.object(main.tempfile, "mkdtemp", return_value=str(work_dir)), patch.object(
                        main, "MAX_FILES", max_files
                    ):
                        with self.assertRaises(HTTPException) as raised:
                            await main.merge_batches_endpoint(BackgroundTasks(), RequestStub(form))

                    self.assertFalse(work_dir.exists())
                self.assertEqual(raised.exception.status_code, status)
                self.assertEqual(raised.exception.detail, detail)

    async def test_upload_limit_is_cumulative_across_batches_and_cleans_workspace(self) -> None:
        manifest = json.dumps(
            [
                {"field": "first", "filename": "One.mp3"},
                {"field": "second", "filename": "Two.mp3"},
            ]
        )
        form = FormStub(
            {"manifest": manifest, "archive_name": "archive.zip"},
            {
                "first": [make_upload("a.mp3", b"a"), make_upload("b.mp3", b"b")],
                "second": [make_upload("c.mp3", b"c"), make_upload("d.mp3", b"d")],
            },
        )

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            output_path.write_bytes(b"ID3")

        with tempfile.TemporaryDirectory() as parent:
            work_dir = Path(tempfile.mkdtemp(dir=parent))
            with (
                patch.object(main.tempfile, "mkdtemp", return_value=str(work_dir)),
                patch.object(main, "MAX_FILES", 100),
                patch.object(main, "MAX_TOTAL_BYTES", 3),
                patch.object(main, "CHUNK_SIZE", 1),
                patch.object(main, "merge_mp3", side_effect=merge_stub),
            ):
                with self.assertRaises(HTTPException) as raised:
                    await main.merge_batches_endpoint(BackgroundTasks(), RequestStub(form))

            self.assertFalse(work_dir.exists())

        self.assertEqual(raised.exception.status_code, 413)
        self.assertEqual(
            raised.exception.detail,
            "Upload size exceeds the configured limit of 3 bytes.",
        )

    async def test_zip_creation_failure_cleans_workspace(self) -> None:
        form = FormStub(
            {
                "manifest": json.dumps([{"field": "files", "filename": "One.mp3"}]),
                "archive_name": "archive.zip",
            },
            {"files": [make_upload("a.mp3"), make_upload("b.mp3")]},
        )

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            output_path.write_bytes(b"ID3")

        with tempfile.TemporaryDirectory() as parent:
            work_dir = Path(tempfile.mkdtemp(dir=parent))
            with (
                patch.object(main.tempfile, "mkdtemp", return_value=str(work_dir)),
                patch.object(main, "MAX_FILES", 100),
                patch.object(main, "MAX_TOTAL_BYTES", 1_073_741_824),
                patch.object(main, "merge_mp3", side_effect=merge_stub),
                patch.object(main.zipfile, "ZipFile", side_effect=OSError("cannot create archive")),
            ):
                with self.assertRaisesRegex(OSError, "cannot create archive"):
                    await main.merge_batches_endpoint(BackgroundTasks(), RequestStub(form))

            self.assertFalse(work_dir.exists())

    async def test_output_directory_creation_failure_cleans_workspace(self) -> None:
        form = FormStub(
            {
                "manifest": json.dumps([{"field": "files", "filename": "One.mp3"}]),
                "archive_name": "archive.zip",
            }
        )

        with tempfile.TemporaryDirectory() as parent:
            work_dir = Path(tempfile.mkdtemp(dir=parent))
            with (
                patch.object(main.tempfile, "mkdtemp", return_value=str(work_dir)),
                patch.object(Path, "mkdir", side_effect=OSError("cannot create output directory")),
            ):
                with self.assertRaisesRegex(OSError, "cannot create output directory"):
                    await main.merge_batches_endpoint(
                        BackgroundTasks(),
                        RequestStub(form),
                    )

            self.assertFalse(work_dir.exists())

    async def test_server_side_zip_contract_is_preserved(self) -> None:
        manifest = [
            {"field": "first", "filename": "One.mp3", "title": "Custom title"},
            {"field": "second", "filename": "Two.mp3", "title": ""},
        ]
        form = FormStub(
            {"manifest": json.dumps(manifest), "archive_name": "chapters"},
            {
                "first": [make_upload("a.mp3", b"a"), make_upload("b.mp3", b"b")],
                "second": [make_upload("c.mp3", b"c"), make_upload("d.mp3", b"d")],
            },
        )
        captured_titles: list[str | None] = []

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            captured_titles.append(title)
            output_path.write_bytes(f"{title}:{len(input_paths)}".encode())

        with (
            patch.object(main, "MAX_FILES", 100),
            patch.object(main, "MAX_TOTAL_BYTES", 1_073_741_824),
            patch.object(main, "merge_mp3", side_effect=merge_stub),
        ):
            response = await main.merge_batches_endpoint(
                BackgroundTasks(),
                RequestStub(form),
            )

        zip_path = Path(response.path)
        work_dir = zip_path.parent
        self.assertEqual(captured_titles, ["Custom title", "Two"])
        self.assertEqual(response.media_type, "application/zip")
        self.assertEqual(
            response.headers["content-disposition"],
            'attachment; filename="chapters.zip"',
        )
        with zipfile.ZipFile(zip_path) as archive:
            self.assertEqual(archive.namelist(), ["One.mp3", "Two.mp3"])
            self.assertEqual(archive.read("One.mp3"), b"Custom title:2")
            self.assertEqual(archive.read("Two.mp3"), b"Two:2")

        self.assertIsNotNone(response.background)
        await response.background()
        self.assertFalse(work_dir.exists())

    async def test_duplicate_output_name_error_is_unchanged(self) -> None:
        manifest = [
            {"field": "first", "filename": "One.mp3"},
            {"field": "second", "filename": "one.MP3"},
        ]
        form = FormStub(
            {"manifest": json.dumps(manifest), "archive_name": "archive.zip"},
            {
                "first": [make_upload("a.mp3"), make_upload("b.mp3")],
                "second": [make_upload("c.mp3"), make_upload("d.mp3")],
            },
        )

        work_dirs: list[Path] = []

        def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
            work_dirs.append(output_path.parent.parent)
            output_path.write_bytes(b"ID3")

        with (
            patch.object(main, "MAX_FILES", 100),
            patch.object(main, "MAX_TOTAL_BYTES", 1_073_741_824),
            patch.object(main, "merge_mp3", side_effect=merge_stub),
        ):
            with self.assertRaises(HTTPException) as raised:
                await main.merge_batches_endpoint(
                    BackgroundTasks(),
                    RequestStub(form),
                )

        self.assertEqual(raised.exception.status_code, 400)
        self.assertEqual(raised.exception.detail, "Duplicate output filename: one.MP3")
        self.assertEqual(len(work_dirs), 1)
        self.assertFalse(work_dirs[0].exists())


if __name__ == "__main__":
    unittest.main()
