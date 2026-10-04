"""Size limits on what the client uploads.

Two layers: the middleware rejects any oversized request BEFORE Starlette
parses it (otherwise the multipart parser spools it all to disk), and
`read_upload` enforces the per-file limit (audio, photo).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException, UploadFile

from . import config

_CHUNK = 64 * 1024

Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]


async def read_upload(upload: UploadFile, max_bytes: int, what: str = "file") -> bytes:
    """Read an UploadFile in chunks and answer 413 as soon as it passes `max_bytes`."""
    buf = bytearray()
    while chunk := await upload.read(_CHUNK):
        buf += chunk
        if len(buf) > max_bytes:
            mb = max_bytes / (1024 * 1024)
            raise HTTPException(413, f"{what} too large (max {mb:.0f} MB)")
    return bytes(buf)


class _TooLarge(Exception):
    pass


class BodySizeLimitMiddleware:
    """Pure ASGI: 413 when the body is larger than config.MAX_BODY_BYTES.

    Checks Content-Length when present and otherwise counts what arrives
    (chunked uploads). The limit is read per request so tests can lower it.
    """

    def __init__(self, app: Callable[..., Awaitable[None]]) -> None:
        self.app = app

    async def __call__(self, scope: MutableMapping[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = config.MAX_BODY_BYTES
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    too_big = int(value) > limit
                except ValueError:
                    too_big = True
                if too_big:
                    await _reject(send)
                    return
                break

        received = 0
        response_started = False

        async def counting_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise _TooLarge
            return message

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooLarge:
            if not response_started:
                await _reject(send)


async def _reject(send: Send) -> None:
    body = b'{"detail":"request too large"}'
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})
