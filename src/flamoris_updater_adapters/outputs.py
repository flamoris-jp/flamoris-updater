"""Operator-selected media directories, separate from private application state.

Only the wrapper's known output bindings are configurable. No directories,
permissions, provider configuration or existing media are created or changed.
"""

import secrets
import socket
import stat
import subprocess
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit, urlunsplit

import httpx
from pydantic import Field

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Model
from flamoris_update_core.wire import decode, digest, dumps, version

GENERATION = "flamoris-generation-mcp"
TARGET = "/data/music-output"
VARIABLE = "FLAMORIS_YUE2_OUTPUT_ROOT"
INPUT_TARGET = "/data/comfyui-input"
INPUT_VARIABLE = "FLAMORIS_COMFYUI_INPUT_ROOT"


class ConfigureOutputs(Model):
    application_id: ID
    request_key: str = Field(min_length=1, max_length=128)
    directories: dict[Literal["yue2", "comfyui"], str] = Field(min_length=1, max_length=2)


def directory_syntax(value):
    if value == "":
        return
    p = Path(value)
    if (
        len(value) > 4096
        or not p.is_absolute()
        or str(p) != value
        or ".." in p.parts
        or any(c in value for c in ",\n\r\0")
        or len(p.parts) < 3
        or any(
            p.is_relative_to(root)
            for root in (
                "/etc",
                "/usr",
                "/root",
                "/run",
                "/proc",
                "/sys",
                "/dev",
                "/bin",
                "/sbin",
                "/lib",
                "/lib64",
            )
        )
    ):
        raise ValueError("An existing, separate absolute media directory is required")


def writable_by_runtime(source):
    """Ask the kernel about UID/GID 10001, including ACLs and parent traversal."""
    for permission in ("-r", "-w", "-x"):
        try:
            result = subprocess.run(
                [
                    "/usr/bin/setpriv",
                    "--reuid=10001",
                    "--regid=10001",
                    "--clear-groups",
                    "--no-new-privs",
                    "/usr/bin/test",
                    permission,
                    source,
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
                env={"PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        if result.returncode:
            return False
    return True


def check_directory(source, protected):
    directory_syntax(source)
    if not source:
        return
    p = Path(source)
    if any(p.is_relative_to(root) or Path(root).is_relative_to(p) for root in protected):
        raise UpdateError("unsafe_storage", "Media and managed state must be separate")
    try:
        if any(stat.S_ISLNK(parent.lstat().st_mode) for parent in [p, *p.parents]):
            raise UpdateError("unsafe_storage")
        if not p.is_dir() or not writable_by_runtime(source):
            raise UpdateError("unsafe_storage", "Runtime cannot use the existing media directory")
    except OSError:
        raise UpdateError("unsafe_storage", "Existing media directory unavailable") from None


def candidate_profile(profile, directories):
    from .install import DockerApplication

    values = {
        **profile,
        "output_directories": {
            **profile.get("output_directories", {}),
            **{k: v for k, v in directories.items() if k == "yue2"},
        },
        "input_directories": {
            **profile.get("input_directories", {}),
            **{k: v for k, v in directories.items() if k == "comfyui"},
        },
    }
    return decode(DockerApplication, dumps(values))


def supported(app):
    return app.application_id == GENERATION and version(
        (app.components or {}).get("flamoris-generation-controller", "0.0.0")
    ) >= version("1.0.1")


def supported_inputs(app):
    return app.application_id == GENERATION and version(
        (app.components or {}).get("flamoris-generation-controller", "0.0.0")
    ) >= version("1.0.3")


def check_sources(manager, app):
    protected = [manager.root, manager.state, *(m.source for m in app.mounts)]
    if manager.self_configuration:
        protected.append(manager.self_configuration.state_directory)
    sources = [*app.output_directories.values(), *app.input_directories.values()]
    for index, source in enumerate(sources):
        others = [value for i, value in enumerate(sources) if i != index and value]
        check_directory(source, [*protected, *others])


def idle(manager, app):
    from .config import protected_read
    from .install import environment

    env = environment(protected_read(app.environment_file, private=True))
    token = env.get("FLAMORIS_CONTROLLER_TOKEN")
    if not token:
        raise UpdateError("invalid_profile", "Controller connection is required for idle checking")
    u = urlsplit(app.health_url)
    url = urlunsplit((u.scheme, u.netloc, "/api/v1/generation/system.health", "", ""))
    try:
        with manager.client.stream(
            "POST", url, headers={"Authorization": "Bearer " + token}, json={}, timeout=10
        ) as response:
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=65536):
                if len(body) + len(chunk) > 262144:
                    raise UpdateError("outcome_unknown", "Controller idle state unavailable")
                body.extend(chunk)
            raw = bytes(body)
            if response.status_code != 200 or len(raw) > 262144:
                raise UpdateError("outcome_unknown", "Controller idle state unavailable")
        from flamoris_update_core.wire import loads

        health = loads(raw, 262144)
        if health.get("busy") is not False or health.get("active_job_id") is not None:
            raise UpdateError("busy", "Finish generation before changing its media binding")
    except httpx.HTTPError:
        raise UpdateError("outcome_unknown", "Controller idle state unavailable") from None


def admit(manager, args):
    from .journal import exclusive

    binding = digest(dumps({"action": "configure_outputs", "arguments": args.model_dump()}))
    key = digest(dumps({"application": args.application_id, "key": args.request_key}))
    with exclusive(manager.state / "manager.lock"), manager.journal.transaction() as db:
        previous = manager.journal.get("managed_request", key, db)
        if previous:
            if previous["binding"] != binding:
                raise UpdateError("idempotency_conflict")
            return manager.journal.get("managed_job", previous["job_id"], db)
        installed = manager.journal.get("managed_app", args.application_id, db)
        if not installed or installed["phase"] != "succeeded":
            raise UpdateError("not_installed")
        app = candidate_profile(installed["profile"], args.directories)
        if not supported(app):
            raise UpdateError(
                "invalid_profile", "This installed image has no supported output binding"
            )
        if db.execute(
            "SELECT 1 FROM records WHERE kind='managed_job' AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') LIMIT 1"
        ).fetchone():
            raise UpdateError("busy")
        check_sources(manager, app)
        identity = "job-" + secrets.token_hex(16)
        job = dict(
            job_id=identity,
            application_id=args.application_id,
            release=installed["release"],
            from_release=installed["release"],
            action="configure_outputs",
            phase="accepted",
            step=None,
            created_at=int(time.time()),
            host=socket.gethostname(),
            platform=manager.hardware(),
        )
        plan = dict(profile_digest=digest(dumps(installed["profile"])), profile=app.model_dump())
        manager.journal.put("managed_output_configuration", identity, plan, db)
        manager.journal.put("managed_job", identity, job, db)
        manager.journal.put("managed_request", key, dict(binding=binding, job_id=identity), db)
        manager.journal.event(db, "managed_job", identity, "accepted")
    manager.wakeup.set()
    return job


def run(manager, identity):
    from .diagnostics import effect as recorded_effect
    from .diagnostics import failure, recording
    from .install import Configuration, DockerApplication
    from .journal import exclusive

    with exclusive(manager.state / "manager.lock"), recording(manager.journal, identity) as log:
        job = manager.journal.get("managed_job", identity)
        if not job or job["action"] != "configure_outputs" or job["phase"] != "accepted":
            return

        def effect(name, fn):
            job.update(phase="intent", step=name)
            manager.persist("managed_job", identity, job)
            result = recorded_effect(name, fn)
            job.update(phase="running", step=name)
            manager.persist("managed_job", identity, job)
            return result

        try:
            installed = manager.journal.get("managed_app", job["application_id"])
            plan = manager.journal.get("managed_output_configuration", identity)
            if (
                not installed
                or installed["phase"] != "succeeded"
                or digest(dumps(installed["profile"])) != plan["profile_digest"]
            ):
                raise UpdateError("operation_conflict")
            log.secrets.extend(manager.secrets(installed["job_id"]))
            old = decode(DockerApplication, dumps(installed["profile"]))
            app = decode(DockerApplication, dumps(plan["profile"]))
            cfg = Configuration(
                install_profile_version=1,
                expected_hostname=job["host"],
                platform=job["platform"],
                state_directory=str(manager.state / "installer"),
                applications=[app],
            )
            installer = manager.installer(cfg)
            manager.save_layout(identity, app, installer)
            effect("verify_current", lambda: installer._verify_running(old))
            effect("validate_output_directory", lambda: check_sources(manager, app))
            effect("verify_idle", lambda: idle(manager, old))
            retained = manager._retained(old, identity)
            job["retained_candidate"] = retained
            manager.persist("managed_job", identity, job)
            effect("stop", lambda: manager._stop(installer, old, retained))
            effect("switch", lambda: installer._start(app))
            effect("health", lambda: installer.health(app))
            effect("verify_running", lambda: installer._verify_running(app))
            if installed["previous"]:
                installed["older"].append(installed["previous"])
            installed.update(
                profile=app.model_dump(), previous=retained, configuration_job_id=identity
            )
            manager.persist("managed_app", app.application_id, installed)
            job.update(phase="succeeded")
            manager.persist("managed_job", identity, job)
            try:
                recorded_effect("cleanup", lambda: manager._cleanup(installed, previous=False))
            except Exception as error:
                job.update(cleanup_pending=True, cleanup_failure=failure(error))
                manager.persist("managed_job", identity, job)
        except BaseException as error:
            job.update(
                phase="recovery_required",
                error=error.code if isinstance(error, UpdateError) else "outcome_unknown",
                failure=failure(error),
            )
            manager.persist("managed_job", identity, job)
            if not isinstance(error, Exception):
                raise
