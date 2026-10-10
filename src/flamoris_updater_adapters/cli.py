import argparse
import sys
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads

from .artifacts import origin
from .config import Endpoint, protected_read
from .managed import MANAGED_TOOLS
from .webpaths import base_path


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="FLAMORIS Updater dedicated coordinator and ordinary API client"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for action in (
        "install",
        "update",
        "apps",
        "job",
        "start-setup",
        "complete-setup",
        "delete-previous",
        "self-status",
        "self-update",
    ):
        command = commands.add_parser(action, help="Use the same managed operation as Web and MCP")
        command.add_argument("--url", required=True)
        command.add_argument("--public-origin")
        if action in {"install", "update", "start-setup", "complete-setup", "delete-previous"}:
            command.add_argument("--application", required=True)
        if action in {"install", "update", "self-update"}:
            command.add_argument("--release", required=True)
            command.add_argument("--request-key", default=None)
        if action == "install":
            command.add_argument(
                "--settings-file", help="Protected JSON settings, or use Web first setup"
            )
        if action == "job":
            command.add_argument("--job-id", required=True)
    init = commands.add_parser(
        "bootstrap", help="Install Updater services and open Web first setup"
    )
    init.add_argument("--directory", default="/var/lib/flamoris-updater")
    init.add_argument("--root", default="/srv/flamoris/apps")
    init.add_argument("--port", type=int, default=8764)
    init.add_argument("--public-origin")
    init.add_argument(
        "--base-path", type=base_path, default="", help="Public Web/API/MCP prefix, e.g. /updater"
    )
    install = commands.add_parser(
        "install-profile", help="Administrator-only direct installation profile"
    )
    install.add_argument("--profile", required=True)
    install.add_argument("--check", action="store_true")
    serve = commands.add_parser("serve")
    serve.add_argument("--config", required=True)
    call = commands.add_parser("call")
    call.add_argument("--url", required=True)
    call.add_argument(
        "--public-origin", help="Configured coordinator HTTPS origin for loopback/tunnel calls"
    )
    call.add_argument("--tool", choices=list(MANAGED_TOOLS), required=True)
    call.add_argument("--arguments", default="-", help="JSON file or stdin")
    args = parser.parse_args(argv)
    try:
        managed_arguments = None
        if args.command in {
            "install",
            "update",
            "apps",
            "job",
            "start-setup",
            "complete-setup",
            "delete-previous",
            "self-status",
            "self-update",
        }:
            names = {
                "install": "updater_install",
                "update": "updater_update",
                "apps": "updater_apps_list",
                "job": "updater_managed_job_get",
                "start-setup": "updater_install_start",
                "complete-setup": "updater_install_complete",
                "delete-previous": "updater_previous_delete",
                "self-status": "updater_self_status",
                "self-update": "updater_self_update",
            }
            managed_arguments = {}
            if hasattr(args, "application"):
                managed_arguments["application_id"] = args.application
            if hasattr(args, "release"):
                managed_arguments.update(
                    release=args.release, request_key=args.request_key or str(uuid.uuid4())
                )
            if args.command == "install" and args.settings_file:
                managed_arguments["settings"] = loads(
                    protected_read(args.settings_file, private=True)
                )
            if args.command == "apps":
                managed_arguments["refresh"] = True
            if args.command == "job":
                managed_arguments["job_id"] = args.job_id
            args.tool = names[args.command]
            args.command = "call"
        if args.command == "bootstrap":
            from .setup import bootstrap

            result = bootstrap(
                Path(args.directory),
                Path(args.root),
                args.public_origin or f"http://127.0.0.1:{args.port}",
                args.port,
                base_path=args.base_path,
            )
            print(dumps(result).decode())
            return
        if args.command == "install-profile":
            from .install import configured

            installer = configured(args.profile)
            print(dumps(installer.preflight() if args.check else installer.apply()).decode())
            return
        if args.command == "call":
            client = Endpoint(url=args.url).client()
            raw = (
                dumps(managed_arguments)
                if managed_arguments is not None
                else (
                    sys.stdin.buffer.read(1024 * 1024 + 1)
                    if args.arguments == "-"
                    else Path(args.arguments).read_bytes()
                )
            )
            payload = loads(raw)
            headers = {"Content-Type": "application/json"}
            if args.public_origin:
                if origin(args.public_origin) != args.public_origin:
                    raise UpdateError("untrusted_origin")
                headers["Host"] = urlsplit(args.public_origin).netloc
            path = "/api/v1/tools/" + args.tool
            with client.stream(
                "POST",
                args.url.rstrip("/") + path,
                content=dumps(payload),
                headers=headers,
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
        from .bootstrap_cli import main as service_main

        service_main(["serve", "--config", args.config])
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
