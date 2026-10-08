"""Admission covers ASGI streaming and response background work, not just headers."""

import contextlib

from .admission import CURRENT, configured
from .errors import UpdateError


class AdmissionMiddleware:
    def __init__(self, app, *, prefixes=("/api/",), health_paths=("/api/system/status",)):
        self.app, self.prefixes, self.health_paths = app, prefixes, health_paths

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith(self.prefixes)
            or scope["path"] in self.health_paths
        ):
            return await self.app(scope, receive, send)
        started, token = False, None
        gate = configured()

        async def observed(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if ticket is not None and message["status"] >= 500:
                    ticket.known = False
            await send(message)

        try:
            with contextlib.nullcontext() if gate is None else gate.work() as ticket:
                if ticket is not None:
                    token = CURRENT.set(ticket.identity)
                await self.app(scope, receive, observed)
        except UpdateError:
            if started:
                raise
            await send(
                {
                    "type": "http.response.start",
                    "status": 503,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"cache-control", b"no-store"),
                        (b"retry-after", b"60"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b'{"error":"maintenance"}'})
        finally:
            if token is not None:
                CURRENT.reset(token)
