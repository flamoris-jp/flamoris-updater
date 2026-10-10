"""Secret-free, durable effect evidence, independent of executable generations."""

import contextvars
import errno
import re
import time
from contextlib import contextmanager
from pathlib import Path

from pydantic import Field

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Model
from flamoris_update_core.wire import dumps, loads

from .journal import durable_write, exclusive, protected_dir

JOB = r"^job-[0-9a-f]{32}$"
ACTIVE = contextvars.ContextVar("updater_diagnostic", default=None)
MAX_EVENTS = 4096
MAX_ENTRY = 8192


class LogPage(Model):
    application_id: ID
    job_id: str = Field(pattern=JOB)
    after: int = Field(default=0, ge=0, le=MAX_EVENTS)
    limit: int = Field(default=25, ge=1, le=50)


class LayoutRequest(Model):
    application_id: ID
    job_id: str | None = Field(default=None, pattern=JOB)


def failure(error):
    """Never serialize exception text, argv, SQL, HTTP bodies or provider output."""
    code = error.code if isinstance(error, UpdateError) else "outcome_unknown"
    result = {
        "error": code
        if isinstance(code, str) and re.fullmatch(r"[a-z_]{1,64}", code)
        else "outcome_unknown"
    }
    if isinstance(error, (KeyboardInterrupt, SystemExit)):
        result["kind"] = "interrupted"
    elif isinstance(error, OSError):
        result.update(kind="os_error", errno=error.errno)
    else:
        result["kind"] = "operation_error"
    state = getattr(error, "sqlstate", None)
    if isinstance(state, str) and re.fullmatch(r"[A-Z0-9]{5}", state):
        result["sqlstate"] = state
    # Only the fixed runner may attach these typed, non-text diagnostics.
    diagnostic = getattr(error, "diagnostic", {})
    if not isinstance(diagnostic, dict):
        return result
    for key in ("exit_code", "errno", "timeout_seconds"):
        value = diagnostic.get(key)
        if type(value) is int and -65536 <= value <= 86400:
            result[key] = value
    if isinstance(diagnostic.get("kind"), str) and diagnostic["kind"] in {
        "nonzero_exit",
        "timeout",
        "os_error",
    }:
        result["kind"] = diagnostic["kind"]
    if isinstance(diagnostic.get("hint"), str) and diagnostic["hint"] in {
        "storage_full",
        "permission_denied",
        "connection_refused",
        "address_in_use",
        "authentication_failed",
        "missing_path",
        "dependency_conflict",
        "unclassified",
    }:
        result["hint"] = diagnostic["hint"]
    return result


def command_kind(argv):
    if argv[0] == "/usr/bin/docker":
        verbs = {
            "container",
            "image",
            "ls",
            "inspect",
            "rm",
            "load",
            "run",
            "create",
            "start",
            "stop",
            "rename",
        }
        return "docker." + ".".join(a for a in argv[1:3] if a in verbs)
    if argv[0] == "/usr/bin/systemctl":
        return "systemd." + (
            argv[1]
            if argv[1] in {"stop", "start", "enable", "is-active", "show", "daemon-reload"}
            else "command"
        )
    if "-m" in argv and "venv" in argv:
        return "python.create_venv"
    if "-m" in argv and "pip" in argv:
        return "python.pip." + ("install" if "install" in argv else "check")
    return "process.check"


def hint(raw, number=None):
    if number in {errno.ENOSPC, errno.EDQUOT}:
        return "storage_full"
    if number in {errno.EACCES, errno.EPERM}:
        return "permission_denied"
    if number == errno.ENOENT:
        return "missing_path"
    text = raw.lower()
    for label, tokens in {
        "storage_full": (b"no space left", b"disk quota"),
        "permission_denied": (b"permission denied", b"operation not permitted"),
        "connection_refused": (b"connection refused", b"cannot connect to the docker daemon"),
        "address_in_use": (b"address already in use", b"port is already allocated"),
        "authentication_failed": (b"authentication failed", b"password authentication failed"),
        "missing_path": (b"no such file", b"not found"),
        "dependency_conflict": (b"dependency conflict", b"resolutionimpossible"),
    }.items():
        if any(t in text for t in tokens):
            return label
    return "unclassified"


def redact(value, secrets):
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in sorted(set(secrets), key=len, reverse=True):
            if secret:
                value = value.replace(secret, "[redacted]")
    return value


class Log:
    def __init__(self, journal, job_id, secrets=()):
        if not re.fullmatch(JOB, job_id):
            raise UpdateError("invalid_input")
        self.journal, self.job_id, self.secrets = journal, job_id, list(secrets)
        self.step = None

    def append(self, operation, outcome, details=None):
        entry = dict(
            log_version=1,
            job_id=self.job_id,
            time_ms=int(time.time() * 1000),
            step=self.step,
            operation=operation,
            outcome=outcome,
            details=redact(details or {}, self.secrets),
        )
        if len(dumps(entry)) > MAX_ENTRY - 32:
            raise UpdateError("quota_exceeded")
        with self.journal.transaction() as db:
            head = self.journal.get("managed_log_head", self.job_id, db) or {"sequence": 0}
            sequence = head["sequence"] + 1
            if sequence > MAX_EVENTS:
                raise UpdateError("quota_exceeded")
            entry["sequence"] = sequence
            identity = self.job_id + ":" + f"{sequence:08d}"
            self.journal.put("managed_log", identity, entry, db)
            self.journal.put("managed_log_head", self.job_id, {"sequence": sequence}, db)
            self.journal.event(db, "managed_diagnostic", identity, outcome)
        # Atomic complete export. A power loss between DB commit and export can
        # leave a shorter mirror; SQLite is authoritative. No effect runs before
        # both the intent record and this export finish.
        directory = self.journal.directory / "diagnostics"
        protected_dir(directory)
        with exclusive(directory / "export.lock", blocking=True):
            with self.journal.connection() as db:
                rows = db.execute(
                    "SELECT payload FROM records WHERE kind='managed_log' AND id LIKE ? ORDER BY id",
                    (self.job_id + ":%",),
                ).fetchall()
            durable_write(
                directory / (self.job_id + ".jsonl"), b"".join(r[0] + b"\n" for r in rows)
            )

    def page(self, after, limit):
        with self.journal.connection() as db:
            rows = db.execute(
                "SELECT payload FROM records WHERE kind='managed_log' AND id LIKE ? AND id>? ORDER BY id LIMIT ?",
                (self.job_id + ":%", self.job_id + ":" + f"{after:08d}", limit + 1),
            ).fetchall()
        items = [loads(r[0]) for r in rows[:limit]]
        head = self.journal.get("managed_log_head", self.job_id)
        return dict(
            items=items,
            after=after,
            next_after=items[-1]["sequence"] if len(rows) > limit else None,
            complete=len(rows) <= limit,
            has_more=len(rows) > limit,
            last_sequence=items[-1]["sequence"] if items else after,
            recorded=bool(head),
            source="durable_effect_records",
            live_state=False,
        )


@contextmanager
def recording(journal, job_id, secrets=()):
    token = ACTIVE.set(Log(journal, job_id, secrets))
    try:
        yield ACTIVE.get()
    finally:
        ACTIVE.reset(token)


def event(operation, outcome, details=None):
    if log := ACTIVE.get():
        log.append(operation, outcome, details)


def effect(operation, function, details=None):
    log = ACTIVE.get()
    if log is None:
        return function()
    previous = log.step
    log.step = operation if previous is None else previous + "/" + operation
    try:
        log.append(operation, "intent", details)
        started = time.monotonic()
        try:
            result = function()
        except BaseException as error:
            log.append(
                operation,
                "failed",
                {**failure(error), "duration_ms": max(0, int((time.monotonic() - started) * 1000))},
            )
            raise
        log.append(
            operation,
            "completed",
            {"duration_ms": max(0, int((time.monotonic() - started) * 1000))},
        )
        return result
    finally:
        log.step = previous


def observed(command):
    def call(argv, **kwargs):
        return effect(command_kind(argv), lambda: command(argv, **kwargs))

    return call


def save_layout(journal, job_id, layout):
    log = ACTIVE.get()
    layout = redact(layout, log.secrets if log else ())
    layout.update(job_id=job_id, recorded_at_ms=int(time.time() * 1000))
    if len(dumps(layout)) > 256 * 1024:
        raise UpdateError("quota_exceeded")
    with journal.transaction() as db:
        journal.put("managed_layout", job_id, layout, db)
    directory = journal.directory / "diagnostics"
    protected_dir(directory)
    durable_write(directory / (job_id + ".layout.json"), dumps(layout) + b"\n")
    event(
        "layout.candidate",
        "recorded",
        {"release": layout.get("release"), "kind": layout.get("kind")},
    )


def describe(app, root, unit_directory):
    """Typed non-secret deployment bindings, never configuration file contents."""
    result = dict(
        application_id=app.application_id,
        release=app.release,
        kind=app.kind,
        application_root=str(root),
        health_url=app.health_url,
        directories=[d.model_dump() for d in app.directories],
        configuration=[
            dict(path=f.destination, mode=f.mode, uid=f.uid, gid=f.gid, private=f.source.private)
            for f in app.files
        ],
        database=dict(
            name=app.database.name,
            owner_role=app.database.owner,
            runtime_role=app.database.runtime_role,
        )
        if app.database
        else None,
        evidence="recorded_configuration",
        live_state=False,
    )
    if app.kind == "docker":
        result.update(
            container=app.container_name,
            image_id=app.image_id,
            network=app.network,
            environment_file=app.environment_file,
            mounts=[m.model_dump() for m in app.mounts],
            ports=[p.model_dump() for p in app.ports],
        )
    else:
        result.update(
            runtime_directory=app.venv,
            python=app.python,
            units=[dict(name=u.name, path=str(Path(unit_directory) / u.name)) for u in app.units],
        )
    return result
