from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any

from starlette.datastructures import Headers, UploadFile


def make_upload(
    filename: str,
    content: bytes = b"mp3-data",
    content_type: str | None = "audio/mpeg",
) -> UploadFile:
    headers = Headers({"content-type": content_type}) if content_type is not None else Headers()
    return UploadFile(file=BytesIO(content), filename=filename, size=len(content), headers=headers)


class FormStub:
    def __init__(self, values: dict[str, Any], lists: dict[str, list[Any]] | None = None) -> None:
        self._values = values
        self._lists = lists or {}

    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def getlist(self, key: str) -> list[Any]:
        return list(self._lists.get(key, []))


class RequestStub:
    def __init__(self, form: FormStub) -> None:
        self._form = form

    async def form(self) -> FormStub:
        return self._form


@dataclass(frozen=True, slots=True)
class AsgiResponse:
    status: int
    headers: dict[str, str]
    body: bytes


async def asgi_request(
    application: Any,
    method: str,
    path: str,
    *,
    body: bytes = b"",
    headers: dict[str, str] | None = None,
) -> AsgiResponse:
    request_sent = False
    messages: list[dict[str, Any]] = []
    encoded_headers = [
        (name.lower().encode("latin-1"), value.encode("latin-1"))
        for name, value in (headers or {}).items()
    ]
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "http",
        "method": method,
        "root_path": "",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "headers": encoded_headers,
        "client": ("test-client", 12345),
        "server": ("test-server", 80),
    }

    async def receive() -> dict[str, Any]:
        nonlocal request_sent
        if request_sent:
            return {"type": "http.disconnect"}
        request_sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    await application(scope, receive, send)

    start = next(message for message in messages if message["type"] == "http.response.start")
    response_body = b"".join(
        message.get("body", b"")
        for message in messages
        if message["type"] == "http.response.body"
    )
    response_headers = {
        name.decode("latin-1").lower(): value.decode("latin-1")
        for name, value in start["headers"]
    }
    return AsgiResponse(status=start["status"], headers=response_headers, body=response_body)


def encode_multipart_file(
    field: str,
    filename: str,
    content: bytes,
    content_type: str = "audio/mpeg",
) -> tuple[bytes, str]:
    boundary = "mp3-merger-contract-boundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {content_type}\r\n"
        "\r\n"
    ).encode("ascii")
    body += content
    body += f"\r\n--{boundary}--\r\n".encode("ascii")
    return body, boundary
