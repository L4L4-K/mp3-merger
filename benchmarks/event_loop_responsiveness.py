from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path
from unittest.mock import patch

from fastapi import BackgroundTasks

from app import main

TRIALS = 5
BLOCK_SECONDS = 0.15
HEARTBEAT_SECONDS = 0.005


def percentile(values: list[float], percentile_value: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(len(ordered) * percentile_value))
    return ordered[index]


async def run_trial() -> tuple[float, list[float]]:
    stop_heartbeat = asyncio.Event()
    heartbeat_lag: list[float] = []

    async def heartbeat() -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + HEARTBEAT_SECONDS
        while not stop_heartbeat.is_set():
            await asyncio.sleep(max(0.0, deadline - loop.time()))
            now = loop.time()
            heartbeat_lag.append(max(0.0, now - deadline))
            deadline += HEARTBEAT_SECONDS

    async def save_stub(
        files: object,
        work_dir: Path,
        prefix: str,
        total_bytes: dict[str, int],
    ) -> list[Path]:
        del files, prefix, total_bytes
        return [work_dir / "one.mp3", work_dir / "two.mp3"]

    def merge_stub(input_paths: list[Path], output_path: Path, title: str | None) -> None:
        del input_paths, title
        time.sleep(BLOCK_SECONDS)
        output_path.write_bytes(b"ID3")

    heartbeat_task = asyncio.create_task(heartbeat())
    await asyncio.sleep(0)
    started = time.perf_counter()
    try:
        with (
            patch.object(main, "MAX_FILES", 100),
            patch.object(main, "save_uploads", side_effect=save_stub),
            patch.object(main, "merge_mp3", side_effect=merge_stub),
        ):
            response = await main.merge_endpoint(BackgroundTasks(), [object(), object()])
        elapsed = time.perf_counter() - started
        if response.background is not None:
            await response.background()
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    return elapsed, heartbeat_lag


async def benchmark() -> None:
    elapsed_values: list[float] = []
    lag_values: list[float] = []
    for _ in range(TRIALS):
        elapsed, lag = await run_trial()
        elapsed_values.append(elapsed)
        lag_values.extend(lag)

    result = {
        "block_ms": round(BLOCK_SECONDS * 1000, 1),
        "trials": TRIALS,
        "merge_elapsed_median_ms": round(statistics.median(elapsed_values) * 1000, 1),
        "event_loop_lag_p95_ms": round(percentile(lag_values, 0.95) * 1000, 1),
        "event_loop_lag_max_ms": round(max(lag_values) * 1000, 1),
        "heartbeat_samples": len(lag_values),
    }
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(benchmark())
