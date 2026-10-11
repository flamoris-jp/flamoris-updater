"""Offline recovery of a Docker fresh install stopped at image staging only.

The operator must stop the three Updater services before calling this module.
This is not a general retry, database recovery or unmanaged adoption path.
"""

import json
import os
import socket
import stat
from urllib.parse import urlsplit

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import decode, digest, dumps

from .config import protected_read
from .diagnostics import effect as recorded_effect
from .diagnostics import event, failure, recording
from .install import DockerApplication, inputs
from .journal import Journal, exclusive
from .managed import Recipe


def recover(manager, identity, *, apply=False):
    if os.geteuid() != 0:
        raise UpdateError("forbidden")
    with exclusive(manager.state / "manager.lock"):
        job = manager.journal.get("managed_job", identity)
        if not job or job.get("action") != "install" or job.get("phase") != "recovery_required":
            raise UpdateError("recovery_required")
        if job.get("host") != socket.gethostname() or job.get("platform") != manager.hardware():
            raise UpdateError("forbidden")
        if manager.journal.get("managed_app", job["application_id"]):
            raise UpdateError("already_installed")
        with manager.journal.connection() as db:
            busy = db.execute(
                "SELECT 1 FROM records WHERE kind='managed_job' AND id!=? "
                "AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required')",
                (identity,),
            ).fetchone()
        if busy:
            raise UpdateError("busy")
        raw = manager.journal.get("managed_recipe", identity)
        recipe = decode(Recipe, dumps({k: v for k, v in raw.items() if k != "_revision"}))
        if digest(dumps(recipe)) != job["recipe"]:
            raise UpdateError("journal_corrupt")
        cfg = manager._profile(recipe, identity, reuse=True)
        app = cfg.applications[0]
        if not isinstance(app, DockerApplication) or app.database is not None:
            raise UpdateError("invalid_profile")
        journal = Journal(cfg.state_directory)
        record = journal.get("initial_install", app.application_id)
        if not record or (
            record.get("phase"),
            record.get("step"),
            record.get("profile_digest"),
        ) != ("recovery_required", "stage", digest(dumps(cfg))):
            raise UpdateError("recovery_required")
        # The failed stage is the final installer step. No DB/create/run is replayed.
        for item in inputs(app):
            item.verify()
        for directory in app.directories:
            info = os.lstat(directory.path)
            if not stat.S_ISDIR(info.st_mode) or (
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            ) != (directory.uid, directory.gid, directory.mode):
                raise UpdateError("unsafe_storage")
        for copied in app.files:
            actual = protected_read(copied.destination, private=copied.source.private)
            info = os.lstat(copied.destination)
            if digest(actual) != copied.source.digest or (
                info.st_uid,
                info.st_gid,
                stat.S_IMODE(info.st_mode),
            ) != (copied.uid, copied.gid, copied.mode):
                raise UpdateError("artifact_mismatch")
        for mount in app.mounts:
            if not os.path.isdir(mount.source):
                raise UpdateError("invalid_profile")
        installer = manager.installer(cfg)
        names = (
            installer.command(
                ["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"]
            )
            .decode()
            .splitlines()
        )
        if app.container_name in names:
            raise UpdateError("not_empty")
        address = urlsplit(app.health_url)
        with socket.socket(
            socket.AF_INET6 if address.hostname == "::1" else socket.AF_INET
        ) as probe:
            probe.bind((address.hostname, address.port or 80))
        result = {
            "job_id": identity,
            "application_id": app.application_id,
            "release": app.release,
            "phase": "verified_stage_recovery",
            "applied": False,
        }
        if not apply:
            return result

        def persist_initial(phase, step):
            record.update(phase=phase, step=step)
            with journal.transaction() as db:
                journal.put("initial_install", app.application_id, record, db)
                journal.event(db, "initial_install", record["profile_digest"], phase)
            journal.flush_export()

        with recording(manager.journal, identity, manager.secrets(identity)):
            event("recovery.stage_preconditions", "verified", result)
            try:
                job.update(phase="intent", step="recover_stage")
                manager.persist("managed_job", identity, job)
                persist_initial("intent", "stage")
                app = recorded_effect("recovery.stage", lambda: installer._stage(app))
                # Persist intent before creating a container. Any uncertainty here
                # requires inspection rather than this stage-only recovery path.
                persist_initial("intent", "provision")
                recorded_effect("recovery.provision", lambda: installer._start(app, start=False))
                observed = json.loads(
                    installer.command(
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
                    or observed.get("State", {}).get("Running") is not False
                ):
                    raise UpdateError("outcome_unknown")
                persist_initial("awaiting_setup", None)
                manager.save_layout(identity, app, installer)
                manager.persist(
                    "managed_app",
                    app.application_id,
                    {
                        "application_id": app.application_id,
                        "release": app.release,
                        "phase": "awaiting_setup",
                        "profile": app.model_dump(),
                        "previous": None,
                        "older": [],
                        "job_id": identity,
                    },
                )
                job["recovered_failure"] = job.pop("failure", None)
                job.pop("error", None)
                job.update(phase="awaiting_setup", step=None)
                manager.persist("managed_job", identity, job)
                return {**result, "phase": "awaiting_setup", "applied": True}
            except BaseException as error:
                persist_initial("recovery_required", record["step"])
                job.update(
                    phase="recovery_required", error="outcome_unknown", failure=failure(error)
                )
                manager.persist("managed_job", identity, job)
                raise
