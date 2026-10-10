"""Updater bootstrap and browser first setup; public Web runs unprivileged."""

import os
import re
import secrets
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.local_transport import UnixClient
from flamoris_update_core.models import Model
from flamoris_update_core.owner_cli import create_server
from flamoris_update_core.wire import decode, dumps, loads

from .auth import AuthStore, token_hash
from .authority import Authority
from .install import VERSIONS, path, run
from .journal import Journal, durable_write, exclusive
from .managed import MANAGED_TARGETS, MANAGED_TOOLS, Manager, https
from .self_update import SELF, runtime_identity, unit_contents
from .webpaths import base_path


class BootstrapConfig(Model):
    setup_version: Literal[1] = 1
    state_directory: str
    helper_state_directory: str
    root: str
    socket_path: str
    service_uid: int = Field(ge=1)
    service_gid: int = Field(ge=1)
    public_origin: str
    base_path: str = ""
    listen_host: str = "127.0.0.1"
    listen_port: int = Field(default=8764, ge=1, le=65535)
    bootstrap_executable: str | None = None
    unit_directory: str = "/etc/systemd/system"

    @field_validator("base_path")
    @classmethod
    def prefix(cls, value):
        return base_path(value)

    @model_validator(mode="after")
    def origin(self):
        u = urlsplit(self.public_origin)
        if (
            self.listen_host not in {"127.0.0.1", "::1"}
            or u.username
            or u.password
            or u.path
            or u.query
            or u.fragment
            or not u.hostname
        ):
            raise ValueError("A literal loopback listener and exact public origin are required")
        if u.scheme != "https" and not (
            u.scheme == "http"
            and u.hostname in {"127.0.0.1", "::1"}
            and (u.port or 80) == self.listen_port
        ):
            raise ValueError("HTTP is available only on loopback; remote access requires HTTPS")
        for value in [
            self.state_directory,
            self.helper_state_directory,
            self.root,
            self.socket_path,
            self.unit_directory,
            *([self.bootstrap_executable] if self.bootstrap_executable else []),
        ]:
            if (
                not Path(value).is_absolute()
                or ".." in Path(value).parts
                or re.search(r"[\s%\"\\]", value)
            ):
                raise ValueError("Bootstrap paths must be absolute plain paths")
        root = Path(self.root)
        if root in {Path("/"), Path("/etc"), Path("/usr"), Path("/srv"), Path("/opt")} or any(
            root.is_relative_to(p) or p.is_relative_to(root)
            for p in [
                Path(self.state_directory),
                Path(self.helper_state_directory),
                Path(self.socket_path).parent,
            ]
        ):
            raise ValueError("Application storage must be a separate leaf namespace")
        return self


class SetupRequest(Model):
    setup_token: str = Field(min_length=16, max_length=256)
    username: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]{0,127}$")
    password: str = Field(min_length=12, max_length=1024)
    catalog_url: str = Field(max_length=2048)


class LocalCoordinator:
    """Web/MCP/CLI authority adapter for the single managed execution service."""

    def __init__(self, cfg, *, client=None):
        self.cfg = cfg
        self.journal = Journal(Path(cfg.state_directory))
        self.authority = Authority(self.journal, lambda: int(time.time()))
        self.auth = AuthStore(self.journal, self.authority, lambda: int(time.time()))
        self.client = client or UnixClient(cfg.socket_path, expected_uid=0)
        self.profiles = {
            a: SimpleNamespace(id=a, application_id=a, role="application") for a in MANAGED_TARGETS
        }
        self.stopping, self.wakeup = threading.Event(), threading.Event()

    def setup_status(self):
        return {
            "setup_required": not bool(self.journal.get("web_setup", "completed")),
            "root": self.cfg.root,
            "public_origin": self.cfg.public_origin,
        }

    def setup(self, payload):
        args = decode(SetupRequest, dumps(payload))
        https(args.catalog_url)
        with exclusive(self.journal.directory / "setup.lock"):
            if not self.setup_status()["setup_required"]:
                raise UpdateError("already_installed")
            pending = self.journal.get("setup_token", "current")
            if (
                not pending
                or not secrets.compare_digest(pending["hash"], token_hash(args.setup_token))
                or pending["expires"] <= time.time()
            ):
                raise UpdateError("forbidden")
            # Configure the root service first. An interrupted frontend setup can
            # retry exactly the same source and complete the account transaction.
            self.client.call({"action": "configure", "body": {"catalog_url": args.catalog_url}})
            self.auth.user(
                args.username, args.password, ["read", "execute", "operator"], MANAGED_TARGETS
            )
            with self.journal.transaction() as db:
                self.journal.put("web_setup", "completed", {"username": args.username}, db)
                db.execute("DELETE FROM records WHERE kind='setup_token'")
            return {"configured": True}

    def managed_invoke(self, subject, name, payload):
        if self.setup_status()["setup_required"] or name not in MANAGED_TOOLS:
            raise UpdateError("forbidden")
        args = decode(MANAGED_TOOLS[name][0], dumps(payload))
        targets = (
            [SELF]
            if name.startswith("updater_self_") and self.cfg.bootstrap_executable
            else [args.application_id]
            if hasattr(args, "application_id")
            else MANAGED_TARGETS
            if self.cfg.bootstrap_executable
            and name in {"updater_managed_history", "updater_managed_job_get"}
            else list(VERSIONS)
        )
        self.authority.require(subject, MANAGED_TOOLS[name][2], targets)
        return self.client.call({"action": "tool", "body": {"name": name, "arguments": payload}})

    def worker(self, *_):
        self.stopping.wait()


def dispatch(manager, action, raw):
    payload = loads(raw)
    if action == "version" and payload == {}:
        return dumps(runtime_identity())
    if action == "configure" and set(payload) == {"catalog_url"}:
        current = manager.journal.get("manager_config", "source")
        if current and current["url"] == payload["catalog_url"]:
            return dumps({"configured": True})
        return dumps(manager.configure(payload["catalog_url"]))
    if action == "tool" and set(payload) == {"name", "arguments"}:
        return dumps(manager.invoke(payload["name"], payload["arguments"]))
    raise UpdateError("invalid_input")


def helper(cfg):
    if os.geteuid() != 0:
        raise UpdateError("forbidden")
    manager = Manager(cfg.helper_state_directory, cfg.root, self_configuration=cfg)
    socket_cfg = SimpleNamespace(
        socket_path=cfg.socket_path,
        socket_group_id=cfg.service_gid,
        allowed_peer_uids=[cfg.service_uid],
    )
    worker = threading.Thread(target=manager.worker, daemon=True)
    worker.start()
    try:
        with create_server(manager, socket_cfg, lambda: None, dispatch) as server:
            server.serve_forever()
    finally:
        manager.stopping.set()
        manager.wakeup.set()
        worker.join(5)


def bootstrap(
    directory,
    root,
    origin,
    port=8764,
    *,
    command=run,
    account=None,
    executable=None,
    unit_directory="/etc/systemd/system",
    base_path="",
):
    if os.geteuid() != 0:
        raise UpdateError(
            "forbidden", "Run bootstrap as administrator to install the local helper and services"
        )
    base = path(str(directory))
    if base.exists():
        raise UpdateError("not_empty", "Bootstrap never replaces existing state or services")
    # Reuse the installed, protected package/bundle; never git clone or pip-build
    # into production application directories.
    executable = executable or str(
        Path(sys.argv[0]).absolute().with_name("flamoris-updater-service")
    )
    path(executable)
    if account is None:
        import pwd

        try:
            account = pwd.getpwnam("flamoris-updater")
        except KeyError:
            command(
                [
                    "/usr/sbin/useradd",
                    "--system",
                    "--user-group",
                    "--no-create-home",
                    "--shell",
                    "/usr/sbin/nologin",
                    "flamoris-updater",
                ]
            )
            account = pwd.getpwnam("flamoris-updater")
    cfg = BootstrapConfig(
        state_directory=str(base / "web"),
        helper_state_directory=str(base / "helper"),
        root=str(root),
        socket_path="/run/flamoris-updater/manager.sock",
        service_uid=account.pw_uid,
        service_gid=account.pw_gid,
        public_origin=origin,
        base_path=base_path,
        listen_port=port,
        bootstrap_executable=executable,
        unit_directory=str(unit_directory),
    )
    units = unit_contents(cfg, executable, base / "setup.json")
    units["flamoris-updater-supervisor.service"] = (
        "[Unit]\nAfter=network.target\n[Service]\n"
        f"ExecStart={executable} supervise --config {base}/setup.json\nRestart=on-failure\n"
        "[Install]\nWantedBy=multi-user.target\n"
    )
    for name in units:
        if Path(unit_directory, name).exists():
            raise UpdateError("not_empty")
    base.mkdir(parents=True, mode=0o755)
    (base / "web").mkdir(mode=0o700)
    os.chown(base / "web", account.pw_uid, account.pw_gid)
    (base / "helper").mkdir(mode=0o700)
    durable_write(base / "setup.json", dumps(cfg), mode=0o644)
    # Provision frontend state as its service account, without changing ownership
    # of a SQLite connection or its WAL files mid-transaction.
    token = (
        command(
            [
                "/usr/bin/setpriv",
                "--reuid",
                str(account.pw_uid),
                "--regid",
                str(account.pw_gid),
                "--clear-groups",
                executable,
                "token",
                "--config",
                str(base / "setup.json"),
            ]
        )
        .decode()
        .strip()
    )
    if not re.fullmatch(r"[a-zA-Z0-9_-]{32,128}", token):
        raise UpdateError("outcome_unknown")
    for name, content in units.items():
        durable_write(Path(unit_directory) / name, content.encode(), mode=0o644)
    command(["/usr/bin/systemctl", "daemon-reload"])
    command(["/usr/bin/systemctl", "enable", "--now", *units])
    return {
        "url": origin + base_path + ("/" if base_path else ""),
        "setup_token": token,
        "token_expires_seconds": 3600,
    }
