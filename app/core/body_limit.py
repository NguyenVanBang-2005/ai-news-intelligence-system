"""ASGI middleware that refuses oversized request bodies before any parsing."""

import json
from collections.abc import Callable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

TOO_LARGE_MESSAGE = "Request body is too large."


class BodySizeLimitMiddleware:
    """Caps the body of requests to the given paths at `max_bytes()` bytes.

    A Content-Length above the cap is refused without reading anything. Without
    Content-Length (chunked upload) the body is read up to the cap and refused as soon as it
    goes over; a body within the cap is then replayed to the app unchanged.
    """

    def __init__(self, app: ASGIApp, *, paths: set[str], max_bytes: Callable[[], int]):
        self.app = app
        self.paths = paths
        # A callable, so the limit follows settings changed at runtime (and in tests).
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] not in self.paths:
            await self.app(scope, receive, send)
            return

        limit = self.max_bytes()
        declared = dict(scope["headers"]).get(b"content-length")

        if declared is not None:
            try:
                too_large = int(declared) > limit
            except ValueError:
                await _reply(send, 400, "Invalid Content-Length header.")
                return
            if too_large:
                await _reply(send, 413, TOO_LARGE_MESSAGE)
                return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":  # client went away
                return
            body += message.get("body", b"")
            if len(body) > limit:
                await _reply(send, 413, TOO_LARGE_MESSAGE)
                return
            if not message.get("more_body", False):
                break

        replayed = False

        async def replay() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _reply(send: Send, status: int, detail: str) -> None:
    payload = json.dumps({"detail": detail}).encode()
    await send({
        "type": "http.response.start",
        "status": status,
        "headers": [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(payload)).encode()),
            (b"connection", b"close"),
        ],
    })
    await send({"type": "http.response.body", "body": payload})
