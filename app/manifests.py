from __future__ import annotations

import json
from typing import Any, TypedDict

from fastapi import HTTPException


class BatchManifestEntry(TypedDict):
    field: str
    filename: str
    title: str


def parse_batch_manifest(raw_manifest: Any) -> list[BatchManifestEntry]:
    if not isinstance(raw_manifest, str):
        raise HTTPException(status_code=400, detail="Missing batch manifest.")

    try:
        manifest = json.loads(raw_manifest)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Batch manifest is not valid JSON.") from None

    if not isinstance(manifest, list) or not manifest:
        raise HTTPException(status_code=400, detail="At least one batch is required.")

    parsed: list[BatchManifestEntry] = []
    for index, entry in enumerate(manifest, start=1):
        if not isinstance(entry, dict):
            raise HTTPException(status_code=400, detail=f"Batch {index} is invalid.")
        field = entry.get("field")
        filename = entry.get("filename")
        title = entry.get("title")
        if not isinstance(field, str) or not field:
            raise HTTPException(status_code=400, detail=f"Batch {index} is missing a field name.")
        if not isinstance(filename, str) or not filename.strip():
            raise HTTPException(status_code=400, detail=f"Batch {index} is missing an output filename.")
        parsed.append(
            {
                "field": field,
                "filename": filename,
                "title": title if isinstance(title, str) else "",
            }
        )

    return parsed
