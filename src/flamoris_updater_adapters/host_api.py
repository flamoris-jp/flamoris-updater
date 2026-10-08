import argparse
import asyncio
import ssl

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .config import HostAPIConfig, load
from .transport import UnixClient


def create_host_app(client):
    async def forward(request):
        if request.headers.get("content-type", "").split(";", 1)[0] != "application/json":
            raise UpdateError("invalid_input")
        raw = bytearray()
        async for chunk in request.stream():
            if len(raw) + len(chunk) > 1024 * 1024:
                raise UpdateError("quota_exceeded")
            raw.extend(chunk)
        result = await asyncio.to_thread(client.call, loads(bytes(raw)))
        return Response(dumps(result), media_type="application/json")

    async def failure(request, error):
        return JSONResponse(
            error.public() if isinstance(error, UpdateError) else {"error": "outcome_unknown"},
            status_code=403
            if isinstance(error, UpdateError) and error.code == "forbidden"
            else 409,
        )

    return Starlette(
        routes=[
            Route(path, forward, methods=["POST"])
            for path in [
                "/api/v1/deployments/inspect",
                "/api/v1/operations/run",
                "/api/v1/operations/inspect",
                "/api/v1/preparations/abort",
                "/api/v1/controller",
            ]
        ],
        exception_handlers={UpdateError: failure, Exception: failure},
    )


def main():
    parser = argparse.ArgumentParser(description="Unprivileged authenticated host front end")
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    cfg = load(HostAPIConfig, args.config)
    cfg.server_tls.context()
    app = create_host_app(UnixClient(cfg.socket_path, cfg.helper_timeout_seconds))
    uvicorn.run(
        app,
        host=cfg.listen_host,
        port=cfg.listen_port,
        ssl_certfile=cfg.server_tls.cert_file,
        ssl_keyfile=cfg.server_tls.key_file,
        ssl_ca_certs=cfg.server_tls.ca_file,
        ssl_cert_reqs=ssl.CERT_REQUIRED,
        proxy_headers=False,
        access_log=False,
    )
