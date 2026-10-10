import asyncio
import threading
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .journal import exclusive
from .mcp import create_mcp
from .self_update import runtime_identity
from .webpaths import Prefix
from .webpaths import base_path as checked_base_path


class Boundary:
    """Apply byte limits while streaming, origin/Host checks and browser security headers."""

    def __init__(self, app, origin, limit=1024 * 1024):
        self.app, self.origin, self.limit = app, origin, limit
        self.host = urlsplit(origin).netloc

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.lower(): v for k, v in scope["headers"]}
        if headers.get(b"host", b"").decode("ascii", errors="ignore") != self.host or (
            b"origin" in headers
            and headers[b"origin"].decode("ascii", errors="ignore") != self.origin
        ):
            await JSONResponse({"error": "forbidden"}, status_code=403)(scope, receive, send)
            return
        used = 0

        async def bounded():
            nonlocal used
            message = await receive()
            if message["type"] == "http.request":
                used += len(message.get("body", b""))
                if used > self.limit:
                    raise UpdateError("quota_exceeded")
            return message

        async def secured(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"cache-control", b"no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"referrer-policy", b"no-referrer"),
                    (
                        b"content-security-policy",
                        b"default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
                    ),
                    (b"strict-transport-security", b"max-age=31536000"),
                ]
            await send(message)

        await self.app(scope, bounded, secured)


async def body(request: Request):
    if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
        raise UpdateError("invalid_input")
    return await request.body()


def create_app(coordinator, origin, run_worker=True, *, base_path=""):
    """One operator screen; no accounts, sessions, passwords or integration keys."""
    base_path = checked_base_path(base_path)
    static = Path(__file__).parent / "static"
    mcp, manager = create_mcp(coordinator, origin)

    async def index(request):
        return HTMLResponse(
            (static / "managed.html").read_text().replace("__UPDATER_BASE_PATH__", base_path)
        )

    async def invoke(request):
        result = await asyncio.to_thread(
            coordinator.managed_invoke,
            "local",
            request.path_params["name"],
            loads(await body(request)),
        )
        return Response(dumps(result), media_type="application/json")

    async def health(request):
        return JSONResponse(
            {
                **runtime_identity(),
                "journal_version": 1,
                "mode": coordinator.journal.meta("mode"),
                "epoch": int(coordinator.journal.meta("epoch")),
            }
        )

    async def failure(request, error):
        if isinstance(error, UpdateError):
            return JSONResponse(
                error.public(), status_code=413 if error.code == "quota_exceeded" else 409
            )
        return JSONResponse(
            {"error": "outcome_unknown", "message": "Inspect the persisted Job before continuing"},
            status_code=500,
        )

    @asynccontextmanager
    async def lifespan(app):
        with (
            exclusive(coordinator.journal.directory / "coordinator.lock")
            if run_worker
            else nullcontext()
        ):
            worker = None
            if run_worker:
                worker = threading.Thread(target=coordinator.worker, args=(False,), daemon=True)
                worker.start()
            async with manager.run():
                yield
            coordinator.stopping.set()
            coordinator.wakeup.set()
            if worker:
                await asyncio.to_thread(worker.join, 5)

    app = Starlette(
        routes=[
            Route("/", index),
            Route("/health", health),
            Route("/api/v1/tools/{name}", invoke, methods=["POST"]),
            Mount("/static", StaticFiles(directory=static)),
            Route("/mcp", mcp, methods=["GET", "POST", "DELETE"]),
        ],
        exception_handlers={UpdateError: failure, Exception: failure},
        lifespan=lifespan,
    )
    return Boundary(Prefix(app, base_path), origin)
