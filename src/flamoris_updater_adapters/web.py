import asyncio
import secrets
import threading
from contextlib import asynccontextmanager, nullcontext
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Model
from flamoris_update_core.wire import decode, dumps, loads

from .inputs import Facade, GrantRequest
from .journal import exclusive
from .mcp import create_mcp
from .self_update import runtime_identity
from .webpaths import Prefix
from .webpaths import base_path as checked_base_path

SESSION = "__Host-updater-session"
LOGIN = "__Host-updater-login"


class LoginRequest(Model):
    username: ID
    password: str = Field(min_length=1, max_length=1024)


class RevokeRequest(Model):
    authorization_id: ID


class IntegrationRequest(Model):
    label: str = Field(min_length=1, max_length=128)
    execute: bool = True


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


def create_app(coordinator, auth, origin, run_worker=True, *, base_path=""):
    base_path = checked_base_path(base_path)
    facade = Facade(coordinator)
    static = Path(__file__).parent / "static"
    mcp, manager = create_mcp(coordinator, auth, origin)
    secure = urlsplit(origin).scheme == "https"
    session_cookie = SESSION if secure else "updater-local-session"
    login_cookie = LOGIN if secure else "updater-local-login"

    def principal(request: Request, mutation=False):
        authorization = request.headers.get("authorization")
        if authorization is not None:
            if not authorization.startswith("Bearer "):
                raise UpdateError("unauthorized")
            return auth.bearer(authorization[7:])
        session = auth.session(request.cookies.get(session_cookie, ""))
        if mutation and (
            request.headers.get("origin") != origin
            or not secrets.compare_digest(request.headers.get("x-csrf-token", ""), session["csrf"])
        ):
            raise UpdateError("forbidden")
        return session["subject"]

    async def bootstrap(request):
        token = secrets.token_urlsafe(32)
        response = JSONResponse({"csrf_token": token})
        response.set_cookie(
            login_cookie,
            token,
            max_age=300,
            secure=secure,
            httponly=True,
            samesite="strict",
            path="/",
        )
        return response

    async def login(request):
        csrf = request.cookies.get(login_cookie, "")
        if (
            request.headers.get("origin") != origin
            or not csrf
            or not secrets.compare_digest(csrf, request.headers.get("x-csrf-token", ""))
        ):
            raise UpdateError("forbidden")
        args = decode(LoginRequest, await body(request))
        token, csrf = await asyncio.to_thread(
            auth.login,
            args.username,
            args.password,
            request.client.host if request.client else "unknown",
        )
        response = JSONResponse({"subject": args.username, "csrf_token": csrf})
        response.set_cookie(
            session_cookie,
            token,
            max_age=3600,
            secure=secure,
            httponly=True,
            samesite="strict",
            path="/",
        )
        response.delete_cookie(
            login_cookie, path="/", secure=secure, httponly=True, samesite="strict"
        )
        return response

    async def session(request):
        subject = principal(request)
        record = auth.session(request.cookies.get(session_cookie, ""))
        permissions = coordinator.authority.require(subject, "read", [])
        targets = [
            {"id": p.id, "application_id": p.application_id}
            for p in coordinator.profiles.values()
            if p.id in permissions["targets"] and p.role == "application"
        ]
        return JSONResponse(
            {
                "subject": subject,
                "csrf_token": record["csrf"],
                "roles": permissions["roles"],
                "targets": targets,
                "managed": hasattr(coordinator, "managed_invoke"),
            }
        )

    async def logout(request):
        principal(request, mutation=True)
        auth.logout(request.cookies.get(session_cookie, ""))
        response = JSONResponse({"logged_out": True})
        response.delete_cookie(
            session_cookie, path="/", secure=secure, httponly=True, samesite="strict"
        )
        return response

    async def invoke(request):
        subject = principal(request, mutation=True)
        payload = loads(await body(request))
        name = request.path_params["name"]
        if name == "updater_recovery_plan" and payload.get("action") != "verify_recovery":
            raise UpdateError("forbidden")
        result = await asyncio.to_thread(facade.invoke, subject, name, payload)
        return Response(dumps(result), media_type="application/json")

    async def grant(request):
        subject = principal(request, mutation=True)
        args = decode(GrantRequest, await body(request))
        plan, _ = coordinator.plan(args.plan_id)
        if plan.action not in {"update", "install", "verify_recovery"}:
            raise UpdateError("forbidden")
        result = coordinator.authorize(subject, args.caller_id, args.plan_id, args.plan_digest)
        return JSONResponse(result)

    async def revoke(request):
        subject = principal(request, mutation=True)
        args = decode(RevokeRequest, await body(request))
        coordinator.authority.revoke(subject, args.authorization_id)
        return JSONResponse({"revoked": True})

    async def index(request):
        filename = "managed.html" if hasattr(coordinator, "managed_invoke") else "index.html"
        return HTMLResponse(
            (static / filename).read_text().replace("__UPDATER_BASE_PATH__", base_path)
        )

    async def setup_status(request):
        return JSONResponse(
            coordinator.setup_status()
            if hasattr(coordinator, "setup_status")
            else {"setup_required": False}
        )

    async def setup(request):
        if not hasattr(coordinator, "setup") or request.headers.get("origin") != origin:
            raise UpdateError("forbidden")
        return JSONResponse(await asyncio.to_thread(coordinator.setup, loads(await body(request))))

    async def issue_token(request):
        subject = principal(request, mutation=True)
        coordinator.authority.require(subject, "operator", [])
        return JSONResponse({"token": auth.issue_token(subject), "expires_seconds": 86400})

    def integration_owner(request, mutation=False):
        # Service keys cannot issue/rotate keys, even if sent with a browser cookie.
        if request.headers.get("authorization") is not None:
            raise UpdateError("forbidden")
        subject = principal(request, mutation=mutation)
        coordinator.authority.require(subject, "operator", [])
        return subject

    async def integrations(request):
        owner = integration_owner(request, request.method == "POST")
        if request.method == "GET":
            return JSONResponse(auth.integrations(owner))
        args = decode(IntegrationRequest, await body(request))
        return JSONResponse(auth.integration(owner, args.label, execute=args.execute))

    async def integration_change(request):
        owner = integration_owner(request, True)
        identity = request.path_params["identity"]
        if request.path_params["action"] == "revoke":
            decode(Model, await body(request))
            auth.revoke_integration(owner, identity)
            return JSONResponse({"revoked": True})
        if request.path_params["action"] != "rotate":
            raise UpdateError("invalid_input")
        args = decode(IntegrationRequest, await body(request))
        return JSONResponse(
            auth.integration(owner, args.label, execute=args.execute, identity=identity)
        )

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
            status = (
                401
                if error.code == "unauthorized"
                else 403
                if error.code == "forbidden"
                else 429
                if error.code == "rate_limited"
                else 413
                if error.code == "quota_exceeded"
                else 409
            )
            return JSONResponse(error.public(), status_code=status)
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
            Route("/api/v1/bootstrap", bootstrap),
            Route("/api/v1/setup", setup_status),
            Route("/api/v1/setup", setup, methods=["POST"]),
            Route("/api/v1/token", issue_token, methods=["POST"]),
            Route("/api/v1/integrations", integrations, methods=["GET", "POST"]),
            Route("/api/v1/integrations/{identity}/{action}", integration_change, methods=["POST"]),
            Route("/api/v1/login", login, methods=["POST"]),
            Route("/api/v1/session", session),
            Route("/api/v1/logout", logout, methods=["POST"]),
            Route("/api/v1/tools/{name}", invoke, methods=["POST"]),
            Route("/api/v1/grants", grant, methods=["POST"]),
            Route("/api/v1/grants/revoke", revoke, methods=["POST"]),
            Mount("/static", StaticFiles(directory=static)),
            Route("/mcp", mcp, methods=["GET", "POST", "DELETE"]),
        ],
        exception_handlers={UpdateError: failure, Exception: failure},
        lifespan=lifespan,
    )
    return Boundary(Prefix(app, base_path), origin)
