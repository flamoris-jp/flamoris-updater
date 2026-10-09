"""Administrator-only fresh installation, independent of application Owner services.

The local protected profile selects immutable packages and application-owned SQL.
There are no shell hooks, remote arguments, legacy adoption, backups or deletions.
"""

import hashlib
import json
import os
import platform
import re
import socket
import stat
import subprocess
import time
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Digest, Model
from flamoris_update_core.wire import decode, digest, dumps

from .config import protected_read
from .journal import Journal, durable_write, exclusive

VERSIONS = {
    "flamoris-ai-agent": "1.0.0",
    "flamoris-studio": "1.0.0",
    "flamoris-intelligence-mcp": "1.0.0",
    "flamoris-generation-mcp": "1.0.0",
    "flamoris-mcp-hub": "1.0.0",
    "flamoris-gpu-node-manager": "1.2.0",
}
Name = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,62}$")]


def path(value: str) -> Path:
    p = Path(value)
    if not p.is_absolute() or ".." in p.parts or any(c in value for c in "\n\r\x00"):
        raise UpdateError("invalid_profile", "Installation paths must be absolute")
    for parent in reversed([p, *p.parents]):
        if not parent.exists() and not parent.is_symlink():
            continue
        info = parent.lstat()
        sticky_directory = stat.S_ISDIR(info.st_mode) and info.st_mode & stat.S_ISVTX
        if (
            stat.S_ISLNK(info.st_mode)
            or info.st_uid != 0
            or (info.st_mode & 0o022 and not sticky_directory)
        ):
            raise UpdateError("unsafe_storage")
    return p


def absent(value: str):
    p = path(value)
    if p.exists() or p.is_symlink():
        raise UpdateError("not_empty", "Fresh installation never replaces existing paths")


class File(Model):
    path: str
    digest: Digest
    private: bool = False

    def verify(self):
        p = path(self.path)
        info = p.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_nlink != 1
            or info.st_size > 4 * 1024**3
            or (self.private and info.st_mode & 0o077)
        ):
            raise UpdateError("unsafe_storage")
        h = hashlib.sha256()
        with p.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                h.update(chunk)
        if "sha256:" + h.hexdigest() != self.digest:
            raise UpdateError("artifact_mismatch")


class Directory(Model):
    path: str
    uid: int = Field(default=0, ge=0)
    gid: int = Field(default=0, ge=0)
    mode: int = Field(default=0o750, ge=0, le=0o777)


class Copy(Model):
    source: File
    destination: str
    mode: int = Field(default=0o600, ge=0, le=0o777)
    uid: int = Field(default=0, ge=0)
    gid: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def permissions(self):
        if self.mode & 0o022 or (self.source.private and self.mode & 0o007):
            raise ValueError("Configuration must not be publicly writable or expose secrets")
        return self


class Mount(Model):
    source: str
    target: str
    read_only: bool


class Port(Model):
    host: int = Field(gt=0, lt=65536)
    container: int = Field(gt=0, lt=65536)


class Database(Model):
    name: Name
    admin_dsn: File
    owner: Name
    runtime_role: Name
    owner_password: File
    runtime_password: File
    sql_files: list[File] = Field(default_factory=list, max_length=32)
    # Studio's installed image owns Alembic. Agent owns its SQL schema/migrations.
    studio_migration_environment: File | None = None

    @model_validator(mode="after")
    def credentials(self):
        if (
            self.owner == self.runtime_role
            or not all(
                f.private for f in (self.admin_dsn, self.owner_password, self.runtime_password)
            )
            or (self.studio_migration_environment and not self.studio_migration_environment.private)
        ):
            raise ValueError("Separate roles and private credential files are required")
        return self


class Application(Model):
    application_id: str
    release: str
    directories: list[Directory] = Field(default_factory=list, max_length=64)
    files: list[Copy] = Field(default_factory=list, max_length=128)
    database: Database | None = None
    health_url: str
    health_timeout_seconds: int = Field(default=90, ge=1, le=600)

    @model_validator(mode="after")
    def target(self):
        if VERSIONS.get(self.application_id) != self.release:
            raise ValueError("Only the agreed fresh-install releases are supported")
        u = urlsplit(self.health_url)
        if (
            u.scheme != "http"
            or u.hostname not in {"127.0.0.1", "::1"}
            or u.username
            or u.password
            or u.query
            or u.fragment
        ):
            raise ValueError("Health checks must use an explicit local HTTP endpoint")
        roots = [Path(d.path) for d in self.directories]
        for f in self.files:
            if not any(Path(f.destination).is_relative_to(root) for root in roots):
                raise ValueError("Configuration copies must stay in declared new directories")
        if self.database and self.application_id not in {"flamoris-ai-agent", "flamoris-studio"}:
            raise ValueError("Only Agent and Studio own initial databases")
        return self


class DockerApplication(Application):
    kind: Literal["docker"]
    image_archive: File
    image_id: Digest
    container_name: Name
    environment_file: str
    network: Literal["host", "bridge"] = "host"
    ports: list[Port] = Field(default_factory=list, max_length=16)
    mounts: list[Mount] = Field(default_factory=list, max_length=64)
    hostname: Name | None = None

    @model_validator(mode="after")
    def docker(self):
        if self.application_id == "flamoris-gpu-node-manager":
            raise ValueError("GPU Node Manager remains native")
        if self.network == "host" and self.ports:
            raise ValueError("Host networking cannot publish ports")
        if self.environment_file not in {f.destination for f in self.files}:
            raise ValueError("Runtime environment must be copied by this installation")
        env_copy = next(f for f in self.files if f.destination == self.environment_file)
        if not env_copy.source.private or env_copy.uid != 0 or env_copy.mode != 0o600:
            raise ValueError("Runtime environment inputs must remain private")
        if self.application_id == "flamoris-studio" and self.network != "bridge":
            raise ValueError(
                "Studio's fixed wildcard listener requires loopback-published bridge networking"
            )
        roots = [Path(d.path) for d in self.directories]
        for mount in self.mounts:
            if not mount.read_only and not any(
                Path(mount.source).is_relative_to(root) for root in roots
            ):
                raise ValueError("Writable mounts must belong to newly created application storage")
            if not Path(mount.target).is_absolute() or any(
                c in mount.source + mount.target for c in ",\n\r\x00"
            ):
                raise ValueError("Invalid bind mount")
        if self.application_id == "flamoris-ai-agent" and self.database:
            if (self.database.owner, self.database.runtime_role) != (
                "flamoris_ai_owner",
                "flamoris_ai_app",
            ) or not self.database.sql_files:
                raise ValueError("Agent initialization requires its declared schema/role contract")
        if self.application_id == "flamoris-studio" and self.database:
            if self.database.sql_files or self.database.studio_migration_environment is None:
                raise ValueError("Studio initializes through its image's Alembic command")
        if (
            self.application_id in {"flamoris-ai-agent", "flamoris-studio"}
            and self.database is None
        ):
            raise ValueError("Agent and Studio installations require their initial database")
        return self


class Unit(Model):
    name: str = Field(pattern=r"^flamoris-[a-z0-9_.@-]+\.service$")
    source: File


class NativeApplication(Application):
    kind: Literal["native"]
    python: str
    venv: str
    wheels: list[File] = Field(min_length=1, max_length=256)
    units: list[Unit] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def native(self):
        if self.application_id != "flamoris-gpu-node-manager" or self.database:
            raise ValueError("Only the native GPU Node Manager uses this installer")
        if not any(Path(self.venv).is_relative_to(d.path) for d in self.directories):
            raise ValueError("Virtual environment must be in a new application directory")
        if any(not f.path.endswith(".whl") for f in self.wheels):
            raise ValueError("Native installation consumes an offline wheel set")
        if any(d.uid != 0 or d.mode & 0o022 for d in self.directories):
            raise ValueError(
                "Native executable and configuration directories must remain protected"
            )
        return self


class Configuration(Model):
    install_profile_version: Literal[1]
    expected_hostname: str = Field(min_length=1, max_length=253)
    platform: Literal["linux/amd64", "linux/arm64"]
    state_directory: str
    applications: list[
        Annotated[DockerApplication | NativeApplication, Field(discriminator="kind")]
    ] = Field(min_length=1, max_length=6)

    @model_validator(mode="after")
    def identities(self):
        if len({a.application_id for a in self.applications}) != len(self.applications):
            raise ValueError("Duplicate application")
        groups = [
            [a.database.name for a in self.applications if a.database],
            [f.destination for a in self.applications for f in a.files],
            [a.container_name for a in self.applications if isinstance(a, DockerApplication)],
            [
                u.name
                for a in self.applications
                if isinstance(a, NativeApplication)
                for u in a.units
            ],
            [
                r
                for a in self.applications
                if a.database
                for r in (a.database.owner, a.database.runtime_role)
            ],
        ]
        if any(len(items) != len(set(items)) for items in groups):
            raise ValueError("Containers, units, files and database identities must be separate")
        roots = [Path(d.path) for a in self.applications for d in a.directories]
        if any(
            r == Path("/") or r in {Path("/etc"), Path("/opt"), Path("/srv"), Path("/usr")}
            for r in roots
        ) or any(
            a.is_relative_to(b) or b.is_relative_to(a)
            for i, a in enumerate(roots)
            for b in roots[i + 1 :]
        ):
            raise ValueError("Application storage roots must be separate leaf namespaces")
        if any(
            Path(self.state_directory).is_relative_to(r) or r.is_relative_to(self.state_directory)
            for r in roots
        ):
            raise ValueError("Installer history must be outside target storage")
        return self


def run(argv, timeout=300):
    try:
        result = subprocess.run(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=timeout,
            check=True,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"},
        )
        if len(result.stdout) > 1024 * 1024:
            raise UpdateError("outcome_unknown")
        return result.stdout
    except (OSError, subprocess.SubprocessError):
        raise UpdateError(
            "outcome_unknown", "Installation command did not confirm completion"
        ) from None


def inputs(app):
    result = [f.source for f in app.files]
    if isinstance(app, DockerApplication):
        result.append(app.image_archive)
    else:
        result.extend(app.wheels)
        result.extend(u.source for u in app.units)
    if app.database:
        db = app.database
        result += [db.admin_dsn, db.owner_password, db.runtime_password, *db.sql_files]
        if db.studio_migration_environment:
            result.append(db.studio_migration_environment)
    return result


def environment(raw):
    result = {}
    for line in raw.decode().splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or key in result:
            raise UpdateError(
                "invalid_profile", "Use literal, duplicate-free KEY=value environment files"
            )
        result[key] = value
    return result


class Installer:
    def __init__(self, cfg: Configuration, *, command=run, connect=None, health=None):
        self.cfg, self.command = cfg, command
        self.connect = connect or self._connect
        self.health = health or self._health

    @staticmethod
    def _connect(db, database=None):
        import psycopg

        return psycopg.connect(
            protected_read(db.admin_dsn.path, private=True).decode().strip(),
            **({"dbname": database} if database else {}),
            autocommit=True,
        )

    def _health(self, app):
        deadline = time.monotonic() + app.health_timeout_seconds
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=2) as client:
            while True:
                try:
                    if app.application_id == "flamoris-mcp-hub":
                        env = environment(protected_read(app.environment_file, private=True))
                        headers = {
                            "Accept": "application/json,text/event-stream",
                            "Authorization": "Bearer " + env["FLAMORIS_MCP_HUB_CLIENT_TOKEN"],
                        }
                        request = {
                            "jsonrpc": "2.0",
                            "id": "installation-health",
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "flamoris-updater", "version": "1.0.0"},
                            },
                        }
                        with client.stream(
                            "POST", app.health_url, json=request, headers=headers
                        ) as response:
                            if response.status_code == 200:
                                for line in response.iter_lines():
                                    if line.startswith("data: "):
                                        line = line[6:]
                                    if line.startswith("{"):
                                        body = json.loads(line)
                                        if (
                                            body.get("result", {})
                                            .get("serverInfo", {})
                                            .get("version")
                                            == app.release
                                        ):
                                            session = response.headers.get("mcp-session-id")
                                            if session:
                                                client.delete(
                                                    app.health_url,
                                                    headers={**headers, "mcp-session-id": session},
                                                )
                                            return
                    else:
                        r = client.get(app.health_url)
                        if r.status_code == 200:
                            return
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise UpdateError("outcome_unknown", "New application did not become healthy")
                time.sleep(0.25)

    def preflight(self):
        if os.geteuid() != 0 or socket.gethostname() != self.cfg.expected_hostname:
            raise UpdateError("forbidden", "Run locally as the expected host's administrator")
        actual = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
        if self.cfg.platform != actual:
            raise UpdateError("unsupported_platform")
        path(self.cfg.state_directory)
        for app in self.cfg.applications:
            for f in inputs(app):
                f.verify()
            for d in app.directories:
                absent(d.path)
            if isinstance(app, DockerApplication):
                names = self.command(
                    ["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"]
                )
                if app.container_name in names.decode().splitlines():
                    raise UpdateError("not_empty")
                source = next(f.source for f in app.files if f.destination == app.environment_file)
                env = environment(protected_read(source.path, private=source.private))
                if app.network == "host":
                    host_keys = {
                        "flamoris-ai-agent": "AGENT_HTTP_HOST",
                        "flamoris-generation-mcp": "FLAMORIS_HTTP_HOST",
                        "flamoris-intelligence-mcp": "FLAMORIS_INTELLIGENCE_HTTP_HOST",
                    }
                    host_key = host_keys.get(app.application_id)
                    if host_key and env.get(host_key) not in {"127.0.0.1", "::1"}:
                        raise UpdateError(
                            "invalid_profile", "Host-network services must bind loopback explicitly"
                        )
                for mount in app.mounts:
                    if mount.read_only and not any(
                        Path(mount.source).is_relative_to(d.path) for d in app.directories
                    ):
                        if not Path(mount.source).is_absolute() or not Path(mount.source).exists():
                            raise UpdateError(
                                "invalid_profile", "External read-only storage is missing"
                            )
            else:
                path(app.python)
                for unit in app.units:
                    absent("/etc/systemd/system/" + unit.name)
                    fragment = self.command(
                        [
                            "/usr/bin/systemctl",
                            "show",
                            unit.name,
                            "--property=FragmentPath",
                            "--value",
                        ]
                    )
                    if fragment.strip():
                        raise UpdateError("not_empty")
                    content = protected_read(unit.source.path).decode()
                    commands = [
                        line.strip()
                        for line in content.splitlines()
                        if line.strip().startswith("Exec")
                    ]
                    if (
                        len(commands) != 1
                        or not commands[0].startswith(f"ExecStart={app.venv}/bin/gpu-node-manager ")
                        or "\\\n" in content
                    ):
                        raise UpdateError(
                            "invalid_profile", "Native unit must start the installed manager"
                        )
            if app.database:
                self._database_preflight(app)
        return {
            "applications": [
                {"application_id": a.application_id, "release": a.release}
                for a in self.cfg.applications
            ],
            "backup_required": False,
        }

    def _database_preflight(self, app):
        db = app.database
        with self.connect(db) as conn:
            if (
                conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db.name,)).fetchone()
                or conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)", ([db.owner, db.runtime_role],)
                ).fetchone()
            ):
                raise UpdateError(
                    "not_empty", "Application database and dedicated roles must be absent"
                )
        if isinstance(app, DockerApplication):
            from psycopg.conninfo import conninfo_to_dict

            source = next(f.source for f in app.files if f.destination == app.environment_file)
            env = environment(protected_read(source.path, private=source.private))
            admin = conninfo_to_dict(
                protected_read(db.admin_dsn.path, private=True).decode().strip()
            )
            if app.application_id == "flamoris-ai-agent":
                runtime = {
                    "dbname": env.get("PGDATABASE"),
                    "user": env.get("PGUSER"),
                    "host": env.get("PGHOST", ""),
                    "port": env.get("PGPORT", "5432"),
                    "password": env.get("PGPASSWORD"),
                }
            else:
                runtime = conninfo_to_dict(
                    env.get("STUDIO_DATABASE_URL", "").replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    )
                )
            if (
                runtime.get("dbname") != db.name
                or runtime.get("user") != db.runtime_role
                or runtime.get("password")
                != protected_read(db.runtime_password.path, private=True).decode().rstrip("\n")
                or any(
                    runtime.get(k, "5432" if k == "port" else "")
                    != admin.get(k, "5432" if k == "port" else "")
                    for k in ("host", "port")
                )
            ):
                raise UpdateError(
                    "invalid_profile",
                    "Runtime credentials must target the new database and runtime role",
                )
        if db.studio_migration_environment:
            from psycopg.conninfo import conninfo_to_dict

            env = environment(protected_read(db.studio_migration_environment.path, private=True))
            url = env.get("STUDIO_DATABASE_URL", "").replace(
                "postgresql+psycopg://", "postgresql://", 1
            )
            target = conninfo_to_dict(url)
            admin = conninfo_to_dict(
                protected_read(db.admin_dsn.path, private=True).decode().strip()
            )
            if (
                target.get("dbname") != db.name
                or target.get("user") != db.owner
                or target.get("password")
                != protected_read(db.owner_password.path, private=True).decode().rstrip("\n")
                or any(
                    target.get(k, "5432" if k == "port" else "")
                    != admin.get(k, "5432" if k == "port" else "")
                    for k in ("host", "port")
                )
            ):
                raise UpdateError(
                    "invalid_profile", "Studio migration must target the new database and owner"
                )

    def _database_create(self, app):
        from psycopg import sql

        db = app.database
        with self.connect(db) as conn:
            for role, password in (
                (db.owner, db.owner_password),
                (db.runtime_role, db.runtime_password),
            ):
                value = protected_read(password.path, private=True).decode().rstrip("\n")
                conn.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                    ).format(sql.Identifier(role), sql.Literal(value))
                )
            conn.execute(
                sql.SQL("CREATE DATABASE {} OWNER {}").format(
                    sql.Identifier(db.name), sql.Identifier(db.owner)
                )
            )
            conn.execute(
                sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db.name))
            )
            conn.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(db.name), sql.Identifier(db.runtime_role)
                )
            )
        with self.connect(db, db.name) as conn:
            for f in db.sql_files:
                f.verify()
                conn.execute(protected_read(f.path, limit=16 * 1024**2).decode())
        if db.studio_migration_environment:
            self.command(
                [
                    "/usr/bin/docker",
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "--env-file",
                    db.studio_migration_environment.path,
                    app.image_id,
                    "alembic",
                    "upgrade",
                    "head",
                ],
                timeout=300,
            )
        with self.connect(db, db.name) as conn:
            schemas = (
                ["public"]
                if app.application_id == "flamoris-studio"
                else ["core", "runtime", "chat", "memory", "relay", "ops"]
            )
            for schema in schemas:
                conn.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(db.runtime_role)
                    )
                )
                conn.execute(
                    sql.SQL(
                        "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO {}"
                    ).format(sql.Identifier(schema), sql.Identifier(db.runtime_role))
                )
                conn.execute(
                    sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(db.runtime_role)
                    )
                )
                for privileges, objects in (
                    ("SELECT,INSERT,UPDATE,DELETE", "TABLES"),
                    ("USAGE,SELECT", "SEQUENCES"),
                ):
                    conn.execute(
                        sql.SQL(
                            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT "
                            + privileges
                            + " ON "
                            + objects
                            + " TO {}"
                        ).format(
                            sql.Identifier(db.owner),
                            sql.Identifier(schema),
                            sql.Identifier(db.runtime_role),
                        )
                    )

    def _files(self, app):
        for d in app.directories:
            absent(d.path)
            Path(d.path).mkdir(parents=True, mode=d.mode)
        for f in app.files:
            p = Path(f.destination)
            p.parent.mkdir(parents=True, exist_ok=True)
            durable_write(p, protected_read(f.source.path, private=f.source.private), mode=f.mode)
            os.chown(p, f.uid, f.gid)
        # Ownership is applied only to new, explicit roots, never external model trees.
        for d in app.directories:
            os.chown(d.path, d.uid, d.gid)
            os.chmod(d.path, d.mode)

    def _stage(self, app):
        if isinstance(app, DockerApplication):
            self.command(
                ["/usr/bin/docker", "load", "--input", app.image_archive.path], timeout=600
            )
            image = json.loads(self.command(["/usr/bin/docker", "image", "inspect", app.image_id]))[
                0
            ]
            labels = image.get("Config", {}).get("Labels") or {}
            if (
                image.get("Id") != app.image_id
                or labels.get("org.opencontainers.image.version") != app.release
                or labels.get("org.opencontainers.image.title") != app.application_id
                or image.get("Config", {}).get("Volumes")
                or image.get("Os") != "linux"
                or image.get("Architecture") != self.cfg.platform.split("/")[1]
            ):
                raise UpdateError("artifact_mismatch")
            if app.application_id == "flamoris-generation-mcp" and json.loads(
                labels.get("net.flamoris.components", "{}")
            ) != {"flamoris-generation-controller": "1.0.0"}:
                raise UpdateError(
                    "artifact_mismatch", "Generation must include its matched Controller"
                )
        else:
            self.command([app.python, "-m", "venv", app.venv])
            self.command(
                [
                    app.venv + "/bin/python",
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    *[f.path for f in app.wheels],
                ],
                timeout=600,
            )
            self.command([app.venv + "/bin/python", "-m", "pip", "check"])
            result = self.command(
                [
                    app.venv + "/bin/python",
                    "-c",
                    "import importlib.metadata; print(importlib.metadata.version('flamoris-gpu-node-manager'))",
                ]
            )
            if result.strip().decode() != app.release:
                raise UpdateError("artifact_mismatch")

    def _start(self, app):
        if isinstance(app, DockerApplication):
            argv = [
                "/usr/bin/docker",
                "run",
                "--detach",
                "--name",
                app.container_name,
                "--restart",
                "unless-stopped",
                "--init",
                "--read-only",
                "--no-healthcheck",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=64m",
                "--user",
                "10001:10001",
                "--network",
                app.network,
                "--env-file",
                app.environment_file,
            ]
            if app.hostname:
                argv += ["--hostname", app.hostname]
            for port in app.ports:
                argv += ["--publish", f"127.0.0.1:{port.host}:{port.container}"]
            for m in app.mounts:
                argv += [
                    "--mount",
                    f"type=bind,src={m.source},dst={m.target}"
                    + (",readonly" if m.read_only else ""),
                ]
            if app.application_id == "flamoris-mcp-hub":
                env = environment(protected_read(app.environment_file, private=True))
                port = env.get("FLAMORIS_MCP_HUB_PORT", "8765")
                if not port.isdecimal() or not 1 <= int(port) <= 65535:
                    raise UpdateError("invalid_profile")
                self.command(
                    [
                        *argv,
                        app.image_id,
                        "flamoris-mcp-hub",
                        "--host",
                        "127.0.0.1" if app.network == "host" else "0.0.0.0",
                        "--port",
                        port,
                        "--mcp-path",
                        "/mcp",
                    ]
                )
            else:
                self.command([*argv, app.image_id])
        else:
            for unit in app.units:
                durable_write(
                    Path("/etc/systemd/system") / unit.name,
                    protected_read(unit.source.path),
                    mode=0o644,
                )
            self.command(["/usr/bin/systemctl", "daemon-reload"])
            self.command(["/usr/bin/systemctl", "enable", "--now", *[u.name for u in app.units]])

    def _verify_running(self, app):
        if isinstance(app, DockerApplication):
            observed = json.loads(
                self.command(
                    [
                        "/usr/bin/docker",
                        "container",
                        "inspect",
                        "--format",
                        "{{json .}}",
                        app.container_name,
                    ]
                )
            )
            if (
                observed.get("Image") != app.image_id
                or observed.get("State", {}).get("Running") is not True
            ):
                raise UpdateError("outcome_unknown")
        else:
            for u in app.units:
                if self.command(["/usr/bin/systemctl", "is-active", u.name]).strip() != b"active":
                    raise UpdateError("outcome_unknown")

    def apply(self):
        directory = path(self.cfg.state_directory)
        journal = Journal(directory)
        binding = digest(dumps(self.cfg))
        with exclusive(directory / "initial-install.lock"):
            previous = journal.get("initial_install", "host")
            if previous:
                raise UpdateError(
                    "already_installed"
                    if previous["phase"] == "succeeded"
                    else "recovery_required",
                    "Inspect the recorded installation; effects are never automatically replayed",
                )
            self.preflight()
            record = {
                "profile_digest": binding,
                "phase": "accepted",
                "application_id": None,
                "step": None,
            }

            def persist():
                with journal.transaction() as db:
                    journal.put("initial_install", "host", record, db)
                    journal.event(db, "initial_install", "host", record["phase"])
                journal.flush_export()

            persist()
            try:
                for app in self.cfg.applications:
                    steps = [("files", self._files), ("stage", self._stage)]
                    if app.database:
                        steps.append(("database", self._database_create))
                    steps += [
                        ("start", self._start),
                        ("health", self.health),
                        ("verify_running", self._verify_running),
                    ]
                    for name, effect in steps:
                        for f in inputs(app):
                            f.verify()
                        record.update(phase="intent", application_id=app.application_id, step=name)
                        persist()
                        effect(app)
                        record["phase"] = "step_succeeded"
                        persist()
                record.update(phase="succeeded", application_id=None, step=None)
                persist()
                return {
                    "phase": "succeeded",
                    "applications": [
                        {"application_id": a.application_id, "release": a.release}
                        for a in self.cfg.applications
                    ],
                    "backup_created": False,
                }
            except BaseException:
                record["phase"] = "recovery_required"
                persist()
                raise


def configured(filename):
    path(filename)
    return Installer(decode(Configuration, protected_read(filename, private=True, root_only=True)))
