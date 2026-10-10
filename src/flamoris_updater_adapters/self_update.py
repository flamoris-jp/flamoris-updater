"""Bootstrap-pinned supervisor for updating Web and manager together.

The supervisor keeps its original installation. It does not replace itself,
restore databases, replay interrupted effects or roll back control records.
"""

import os
import secrets
import socket
import threading
import time
from importlib.metadata import version as package_version
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Artifact, Model
from flamoris_update_core.wire import decode, digest, dumps, loads, version

from .artifacts import Fetcher, NativeStore, origin
from .compatibility import bundle_metadata, probe_candidate
from .diagnostics import effect as recorded_effect
from .diagnostics import event, failure, observed, recording, save_layout
from .install import path, run
from .journal import Journal, durable_write, exclusive

SELF = "flamoris-updater"


class SelfRelease(Model):
    release: str
    compatible_from: list[str] = Field(max_length=128)
    artifact: Artifact
    supervisor_protocol_version: Literal[1] = 1

    @model_validator(mode="after")
    def supported(self):
        if self.artifact.kind != "native" or version(self.release) < version("1.0.0"):
            raise ValueError("Updater requires an indexed Native bundle")
        origin(self.artifact.locator)
        for previous in self.compatible_from:
            version(previous)
        return self


class SelfStart(Model):
    release: str
    request_key: str = Field(min_length=1, max_length=128)


def runtime_identity():
    return {
        "version": package_version(SELF),
        "supervisor_protocol_version": 1,
        "integration_auth_version": 1,
        "runtime_root": str(Path(__file__).resolve().parent.parent),
    }


def unit_contents(cfg, executable, config_path):
    """Only fixed bootstrap bindings may be carried into candidate units."""
    account = f"User={cfg.service_uid}\nGroup={cfg.service_gid}\n"
    common = f" --config {config_path}\nRestart=on-failure\n"
    return {
        "flamoris-updater.service": "[Unit]\nAfter=network.target flamoris-updater-manager.service\nRequires=flamoris-updater-manager.service\n[Service]\n"
        + account
        + f"ExecStart={executable} serve"
        + common
        + "NoNewPrivileges=yes\nPrivateTmp=yes\n[Install]\nWantedBy=multi-user.target\n",
        "flamoris-updater-manager.service": "[Unit]\nAfter=network.target docker.service\n[Service]\n"
        + f"Group={cfg.service_gid}\nRuntimeDirectory=flamoris-updater\nRuntimeDirectoryMode=0750\nExecStart={executable} helper"
        + common
        + "[Install]\nWantedBy=multi-user.target\n",
    }


def initial_record(cfg):
    return {
        "release": package_version(SELF),
        "runtime": str(Path(cfg.bootstrap_executable).parent.parent),
        "phase": "succeeded",
        "previous": None,
        "job_id": None,
    }


def deployment_layout(cfg, installation, config_path=None):
    return {
        "application_id": SELF,
        "kind": "updater",
        "release": installation["release"],
        "runtime_directory": installation["runtime"],
        "job_id": installation.get("job_id"),
        "installation_phase": installation["phase"],
        "host": socket.gethostname(),
        "configuration_file": str(config_path or Path(cfg.state_directory).parent / "setup.json"),
        "web_state_directory": cfg.state_directory,
        "manager_state_directory": cfg.helper_state_directory,
        "diagnostics_directory": str(Path(cfg.helper_state_directory) / "diagnostics"),
        "application_storage": cfg.root,
        "manager_socket": cfg.socket_path,
        "public_origin": cfg.public_origin,
        "base_path": getattr(cfg, "base_path", ""),
        "mcp_url": cfg.public_origin + getattr(cfg, "base_path", "") + "/mcp",
        "bootstrap_executable": cfg.bootstrap_executable,
        "units": [
            {
                "name": name,
                "path": str(Path(cfg.unit_directory) / name),
                "executable": cfg.bootstrap_executable
                if name.endswith("supervisor.service")
                else str(Path(installation["runtime"]) / "bin/flamoris-updater-service"),
            }
            for name in (
                "flamoris-updater.service",
                "flamoris-updater-manager.service",
                "flamoris-updater-supervisor.service",
            )
        ],
        "previous": installation.get("previous"),
        "evidence": "recorded_configuration",
        "live_state": False,
    }


def admit(manager, args):
    cfg = manager.self_configuration
    if cfg is None or cfg.bootstrap_executable is None:
        raise UpdateError("unsupported_migration", "Self-update requires the supervisor bootstrap")
    recipe = next(
        (
            r
            for r in manager.catalog().updater_releases
            if r.release == args.release and r.artifact.platform == manager.hardware()
        ),
        None,
    )
    if recipe is None:
        raise UpdateError("release_unavailable")
    binding = digest(dumps({"request": args.model_dump(), "recipe": recipe.model_dump()}))
    key = digest(dumps({"application": SELF, "key": args.request_key}))
    with exclusive(manager.state / "manager.lock"), manager.journal.transaction() as db:
        prior = manager.journal.get("managed_request", key, db)
        if prior:
            if prior["binding"] != binding:
                raise UpdateError("idempotency_conflict")
            return manager.journal.get("managed_job", prior["job_id"], db)
        installed = manager.journal.get("self_installation", "current", db)
        if (
            installed is None
            or installed["phase"] != "succeeded"
            or installed["release"] not in recipe.compatible_from
            or version(args.release) <= version(installed["release"])
        ):
            raise UpdateError("unsupported_migration")
        if db.execute(
            "SELECT 1 FROM records WHERE kind='managed_job' AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') LIMIT 1"
        ).fetchone():
            raise UpdateError("busy")
        job_id = "job-" + secrets.token_hex(16)
        job = {
            "job_id": job_id,
            "application_id": SELF,
            "action": "self_update",
            "release": args.release,
            "from_release": installed["release"],
            "phase": "accepted",
            "step": None,
            "created_at": int(time.time()),
            "recipe": digest(dumps(recipe)),
            "steps": [],
            "retained_candidate": installed,
            "host": socket.gethostname(),
            "platform": manager.hardware(),
        }
        manager.journal.put("managed_self_recipe", job_id, recipe.model_dump(), db)
        manager.journal.put("managed_job", job_id, job, db)
        manager.journal.put("managed_request", key, {"binding": binding, "job_id": job_id}, db)
        manager.journal.event(db, "self_update_accepted", job_id)
    manager.journal.flush_export()
    return job


class Supervisor:
    def __init__(self, cfg, config_path, *, command=run, client=None, store=None):
        if os.geteuid() != 0 or not cfg.bootstrap_executable:
            raise UpdateError("forbidden")
        self.cfg, self.config_path = cfg, path(str(config_path))
        self.state = path(cfg.helper_state_directory)
        self.journal = Journal(self.state)
        self.raw_command = command
        self.command = observed(command)
        self.client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=5)
        self.store = store
        self.stopping = threading.Event()

    def persist(self, job):
        with self.journal.transaction() as db:
            self.journal.put("managed_job", job["job_id"], job, db)
            self.journal.event(
                db, "self_update_" + (job["step"] or "state"), job["job_id"], job["phase"]
            )
        self.journal.flush_export()
        event("job.state", job["phase"], {"step": job.get("step"), "error": job.get("error")})

    def candidate(self, release):
        store = self.store or NativeStore(
            path(str(self.state.parent / "releases")),
            Fetcher([origin(release.artifact.locator)], self.client),
        )
        directory = store.prepare(release.artifact)
        store.verify(directory, release.artifact)
        if bundle_metadata(directory)["version"] != release.release:
            raise UpdateError("artifact_mismatch")
        executable = directory / "bin/flamoris-updater-service"
        path(str(executable))
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise UpdateError("unsafe_artifact")
        identity = loads(
            self.command([str(executable), "check", "--config", str(self.config_path)], timeout=30)
        )
        if identity != {
            "version": release.release,
            "supervisor_protocol_version": 1,
            "integration_auth_version": 1,
            "runtime_root": str(directory / "site-packages"),
        }:
            raise UpdateError("unsupported_journal")
        return directory, executable, store

    def bindings(self):
        from .config import load

        if load(type(self.cfg), str(self.config_path), root_only=True) != self.cfg:
            raise UpdateError("operation_conflict")
        current = self.journal.get("self_installation", "current")
        executable = (
            self.cfg.bootstrap_executable
            if current["job_id"] is None
            else str(Path(current["runtime"]) / "bin/flamoris-updater-service")
        )
        for name, content in unit_contents(self.cfg, executable, self.config_path).items():
            destination = path(str(Path(self.cfg.unit_directory) / name))
            if not destination.is_file() or destination.read_text() != content:
                raise UpdateError("operation_conflict")

    def probe(self, release, executable):
        wanted = {
            "version": release.release,
            "supervisor_protocol_version": 1,
            "integration_auth_version": 1,
            "runtime_root": str(executable.parent.parent / "site-packages"),
        }
        self.command(
            [
                "/usr/bin/systemctl",
                "is-active",
                "flamoris-updater.service",
                "flamoris-updater-manager.service",
            ]
        )
        deadline = time.monotonic() + 30
        host = "[::1]" if self.cfg.listen_host == "::1" else self.cfg.listen_host
        while True:
            try:
                live = loads(
                    self.command(
                        [
                            "/usr/bin/setpriv",
                            "--reuid",
                            str(self.cfg.service_uid),
                            "--regid",
                            str(self.cfg.service_gid),
                            "--clear-groups",
                            str(executable),
                            "probe",
                            "--config",
                            str(self.config_path),
                        ],
                        timeout=5,
                    )
                )
                response = self.client.get(
                    f"http://{host}:{self.cfg.listen_port}{self.cfg.base_path}/health",
                    headers={"Host": urlsplit(self.cfg.public_origin).netloc},
                )
                if (
                    live == wanted
                    and response.status_code == 200
                    and all(response.json().get(k) == v for k, v in wanted.items())
                ):
                    return {"web_version": release.release, "manager_version": release.release}
            except (httpx.HTTPError, ValueError, UpdateError):
                pass
            if time.monotonic() >= deadline:
                raise UpdateError("outcome_unknown")
            time.sleep(0.25)

    def run_job(self, identity):
        with exclusive(self.state / "manager.lock"), recording(self.journal, identity):
            job = self.journal.get("managed_job", identity)
            if not job or job["action"] != "self_update" or job["phase"] != "accepted":
                return

            def effect(name, function):
                job.update(step=name, phase="intent")
                job["steps"].append({"step": name, "outcome": "intent", "time": int(time.time())})
                self.persist(job)
                result = recorded_effect(name, function)
                job.update(phase="running")
                job["steps"].append({"step": name, "outcome": "verified", "time": int(time.time())})
                self.persist(job)
                return result

            try:
                event(
                    "job.accepted",
                    "recorded",
                    {
                        k: job.get(k)
                        for k in (
                            "application_id",
                            "action",
                            "release",
                            "from_release",
                            "recipe",
                            "host",
                            "platform",
                            "created_at",
                        )
                    },
                )
                self.bindings()
                raw = self.journal.get("managed_self_recipe", identity)
                release = decode(
                    SelfRelease, dumps({k: v for k, v in raw.items() if k != "_revision"})
                )
                if digest(dumps(release)) != job["recipe"]:
                    raise UpdateError("journal_corrupt")
                directory, executable, store = effect("stage", lambda: self.candidate(release))
                job["candidate_runtime"] = str(directory)
                layout = deployment_layout(
                    self.cfg,
                    {"release": release.release, "runtime": str(directory), "phase": "candidate"},
                    self.config_path,
                )
                previous = self.journal.get("self_installation", "current")
                layout["previous_layout"] = deployment_layout(self.cfg, previous, self.config_path)
                save_layout(self.journal, identity, layout)
                self.persist(job)
                # No app work can be admitted while this Job is active.
                effect(
                    "stop",
                    lambda: self.command(
                        [
                            "/usr/bin/systemctl",
                            "stop",
                            "flamoris-updater.service",
                            "flamoris-updater-manager.service",
                        ]
                    ),
                )

                # Control/auth/history remain at their existing paths. The candidate
                # probes both databases read-only and must agree before replacement.
                def check_state():
                    for state in (self.cfg.state_directory, self.cfg.helper_state_directory):
                        probe_candidate(directory, state, self.raw_command, "/usr/bin/python3.12")
                    store.verify(directory, release.artifact)

                effect("control_check", check_state)
                self.bindings()
                units = unit_contents(self.cfg, executable, self.config_path)

                def switch():
                    for name, content in units.items():
                        destination = path(str(Path(self.cfg.unit_directory) / name))
                        if not destination.is_file():
                            raise UpdateError("outcome_unknown")
                        recorded_effect(
                            "unit.write",
                            lambda: durable_write(destination, content.encode(), mode=0o644),
                            {"unit": name, "path": str(destination), "executable": str(executable)},
                        )
                    self.command(["/usr/bin/systemctl", "daemon-reload"])

                effect("switch", switch)
                effect(
                    "start",
                    lambda: self.command(
                        [
                            "/usr/bin/systemctl",
                            "start",
                            "flamoris-updater-manager.service",
                            "flamoris-updater.service",
                        ]
                    ),
                )
                job["verification"] = effect("verify", lambda: self.probe(release, executable))
                previous = self.journal.get("self_installation", "current")
                with self.journal.transaction() as db:
                    self.journal.put(
                        "self_installation",
                        "current",
                        {
                            "release": release.release,
                            "runtime": str(directory),
                            "phase": "succeeded",
                            "previous": {
                                k: v
                                for k, v in previous.items()
                                if k not in {"previous", "_revision"}
                            },
                            "job_id": identity,
                        },
                        db,
                    )
                job.update(phase="succeeded", step="verified")
                self.persist(job)
            except BaseException as error:
                job.update(
                    phase="recovery_required",
                    error=error.code if isinstance(error, UpdateError) else "outcome_unknown",
                    failure=failure(error),
                )
                self.persist(job)
                if not isinstance(error, Exception):
                    raise

    def worker(self):
        with exclusive(self.state / "supervisor.lock"):
            with self.journal.connection() as db:
                interrupted = [
                    loads(r[0])
                    for r in db.execute(
                        "SELECT payload FROM records WHERE kind='managed_job' AND json_extract(payload,'$.action')='self_update' AND json_extract(payload,'$.phase') IN ('running','intent')"
                    )
                ]
            for job in interrupted:
                job.update(
                    phase="recovery_required",
                    error="outcome_unknown",
                    failure={"error": "outcome_unknown", "kind": "interrupted"},
                )
                with recording(self.journal, job["job_id"]):
                    event("job.interrupted", "unknown", {"step": job.get("step")})
                    self.persist(job)
            while not self.stopping.is_set():
                with self.journal.connection() as db:
                    queued = db.execute(
                        "SELECT id FROM records WHERE kind='managed_job' AND json_extract(payload,'$.action')='self_update' AND json_extract(payload,'$.phase')='accepted' LIMIT 1"
                    ).fetchone()
                if queued:
                    try:
                        self.run_job(queued[0])
                    except UpdateError as error:
                        if error.code != "busy":
                            raise
                self.stopping.wait(1)
