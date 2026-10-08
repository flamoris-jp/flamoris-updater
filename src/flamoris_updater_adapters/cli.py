import argparse
import getpass
import sys
from pathlib import Path

import httpx
import uvicorn

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .config import TLS, Endpoint, protected_read
from .inputs import TOOLS
from .journal import durable_write, exclusive
from .runtime import coordinator
from .web import create_app


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="FLAMORIS Updater dedicated coordinator and ordinary API client"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    serve = commands.add_parser("serve")
    serve.add_argument("--config", required=True)
    call = commands.add_parser("call")
    call.add_argument("--url", required=True)
    call.add_argument("--token-file", required=True)
    call.add_argument("--ca", required=True)
    call.add_argument("--cert", required=True)
    call.add_argument("--key", required=True)
    call.add_argument("--tool", choices=list(TOOLS) + ["grant", "revoke-grant"], required=True)
    call.add_argument("--arguments", default="-", help="JSON file or stdin")
    for name in ("provision-user", "issue-token"):
        command = commands.add_parser(name)
        command.add_argument("--config", required=True)
        command.add_argument("--subject", required=True)
        if name == "provision-user":
            command.add_argument("--roles", required=True)
            command.add_argument("--targets", required=True)
        else:
            command.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "call":
            client = Endpoint(
                url=args.url, tls=TLS(ca_file=args.ca, cert_file=args.cert, key_file=args.key)
            ).client()
            token = protected_read(args.token_file, private=True, limit=256).decode().strip()
            raw = (
                sys.stdin.buffer.read(1024 * 1024 + 1)
                if args.arguments == "-"
                else Path(args.arguments).read_bytes()
            )
            payload = loads(raw)
            path = (
                "/api/v1/grants"
                if args.tool == "grant"
                else "/api/v1/grants/revoke"
                if args.tool == "revoke-grant"
                else "/api/v1/tools/" + args.tool
            )
            with client.stream(
                "POST",
                args.url.rstrip("/") + path,
                content=dumps(payload),
                headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
                follow_redirects=False,
            ) as response:
                parts, size = [], 0
                for part in response.iter_bytes(chunk_size=65536):
                    size += len(part)
                    if size > 2 * 1024 * 1024:
                        raise UpdateError("quota_exceeded")
                    parts.append(part)
                result = loads(b"".join(parts), 2 * 1024 * 1024)
                sys.stdout.buffer.write(dumps(result) + b"\n")
                if response.status_code != 200:
                    raise SystemExit(1)
            return
        cfg, c, auth = coordinator(args.config)
        if args.command == "serve":
            if cfg.server_tls:
                cfg.server_tls.context()
            tls = (
                {"ssl_certfile": cfg.server_tls.cert_file, "ssl_keyfile": cfg.server_tls.key_file}
                if cfg.server_tls
                else {}
            )
            uvicorn.run(
                create_app(c, auth, cfg.public_origin),
                host=cfg.listen_host,
                port=cfg.listen_port,
                proxy_headers=False,
                access_log=False,
                **tls,
            )
        else:
            with exclusive(c.journal.directory / "coordinator.lock"):
                if args.command == "provision-user":
                    if not set(args.targets.split(",")) <= set(c.profiles):
                        raise UpdateError("invalid_input")
                    auth.user(
                        args.subject,
                        getpass.getpass("Operator password: "),
                        args.roles.split(","),
                        args.targets.split(","),
                    )
                else:
                    path = Path(args.output)
                    if not path.is_absolute() or path.exists() or path.is_symlink():
                        raise UpdateError("unsafe_storage")
                    durable_write(path, (auth.issue_token(args.subject) + "\n").encode())
                c.journal.flush_export()
            print(dumps({"completed": args.command, "subject": args.subject}).decode())
    except (UpdateError, httpx.HTTPError) as error:
        sys.stderr.write(
            dumps(
                error.public()
                if isinstance(error, UpdateError)
                else {"error": "coordinator_unavailable"}
            ).decode()
            + "\n"
        )
        raise SystemExit(1) from None
