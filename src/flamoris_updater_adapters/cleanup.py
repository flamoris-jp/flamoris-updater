"""Explicit, observed executable cleanup; no installation or DB input reads."""

import re
import shutil
from pathlib import Path

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import loads, version

from .diagnostics import effect, event
from .install import DockerApplication, NativeApplication, path


def guard(condition, check):
    if not condition:
        event("cleanup.guard", "rejected", {"check": check})
        raise UpdateError("unsafe_storage")


def references(value):
    """All active file inputs, not their contents (including initial DB inputs)."""
    if isinstance(value, dict):
        for key in ("path", "destination", "environment_file", "venv"):
            if isinstance(value.get(key), str):
                yield value[key]
        for child in value.values():
            yield from references(child)
    elif isinstance(value, list):
        for child in value:
            yield from references(child)


def clean(manager, installed, previous):
    current = installed["profile"]
    entries = [
        *installed["older"],
        *([installed["previous"]] if previous and installed["previous"] else []),
    ]
    command = manager.cleanup_command
    runtimes, packages, images = [], [], set()
    retained = [] if previous or not installed["previous"] else [installed["previous"]]
    protected_images = {current.get("image_id"), *(e.get("image_id") for e in retained)}
    protected_paths = {current.get("venv"), *(e.get("path") for e in retained)}
    protected_packages = {installed["job_id"], *(e.get("package_id") for e in retained)}

    def validate():
        guard(installed["phase"] == "succeeded", "successful_installation")
        guard(current.get("application_id") == installed["application_id"], "application_identity")
        (DockerApplication if current["kind"] == "docker" else NativeApplication).model_validate(
            current
        )
        for entry in entries:
            guard(entry.get("kind") == current["kind"], "runtime_kind")
            if entry["kind"] == "native":
                version(entry["release"])
                p = path(entry["path"])
                expected = (
                    manager.root / installed["application_id"] / "releases" / entry["release"]
                )
                guard(p == expected and str(p) not in protected_paths, "native_runtime")
                guard(
                    not any(Path(value).is_relative_to(p) for value in references(current)),
                    "active_runtime_input",
                )
                runtimes.append(p)
            else:
                name, image = entry.get("container", ""), entry.get("image_id", "")
                guard(
                    bool(
                        re.fullmatch(re.escape(current["container_name"]) + r"-[0-9a-f]{12}", name)
                    )
                    and name
                    not in {current["container_name"], *(e.get("container") for e in retained)},
                    "retained_container_identity",
                )
                guard(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", image)), "retained_image_identity")
                images.add(image)
            identity = entry.get("package_id")
            if identity:
                guard(bool(re.fullmatch(r"job-[0-9a-f]{32}", identity)), "package_identity")
                if identity in protected_packages:
                    event("cleanup.package", "retained", {"reason": "active_package"})
                    continue
                package = path(str(manager.state / "packages" / identity))
                if any(Path(p).is_relative_to(package) for p in references(current)):
                    event("cleanup.package", "retained", {"reason": "active_input"})
                else:
                    packages.append(package)

    effect("cleanup.validate", validate)
    observed = {}
    if entries and current["kind"] == "docker":

        def inspect(name):
            return loads(
                command(["/usr/bin/docker", "container", "inspect", "--format", "{{json .}}", name])
            )

        # This observation is separate from installation health and never reads
        # private environment/DB inputs or serializes Docker's raw inspect result.
        running = effect("cleanup.current", lambda: inspect(current["container_name"]))
        guard(
            running.get("Image") == current["image_id"]
            and running.get("State", {}).get("Running") is True,
            "current_runtime",
        )
        names = set(
            command(["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"])
            .decode()
            .splitlines()
        )
        for entry in entries:
            name = entry["container"]
            if name in names:
                state = inspect(name)
                guard(
                    state.get("Image") == entry["image_id"]
                    and state.get("State", {}).get("Running") is False,
                    "stopped_target",
                )
                observed[name] = entry["image_id"]
            else:
                event("cleanup.container", "absent", {"container": name})

    # Explicit retries reconcile each target against real state. A process loss
    # never triggers automatic replay. All targets validate before any deletion.
    event("cleanup.reconcile", "verified", {"targets": len(entries), "delete_previous": previous})
    for name, image in observed.items():
        # Recheck after preflight, retaining Docker's own no-force running guard.
        state = inspect(name)
        guard(
            state.get("Image") == image and state.get("State", {}).get("Running") is False,
            "stopped_target",
        )
        effect(
            "cleanup.container",
            lambda: command(["/usr/bin/docker", "container", "rm", name]),
            {"container": name, "image_id": image},
        )
    if images:
        present = set(
            command(["/usr/bin/docker", "image", "ls", "--no-trunc", "--quiet"])
            .decode()
            .splitlines()
        )
        for image in sorted(images):
            if image in protected_images:
                event(
                    "cleanup.image", "retained", {"image_id": image, "reason": "retained_runtime"}
                )
            elif image not in present:
                event("cleanup.image", "absent", {"image_id": image})
            elif command(
                [
                    "/usr/bin/docker",
                    "container",
                    "ls",
                    "--all",
                    "--filter",
                    "ancestor=" + image,
                    "--format",
                    "{{.Names}}",
                ]
            ).strip():
                event(
                    "cleanup.image",
                    "retained",
                    {"image_id": image, "reason": "container_reference"},
                )
            else:
                effect(
                    "cleanup.image",
                    lambda: command(["/usr/bin/docker", "image", "rm", image]),
                    {"image_id": image},
                )
    for p in dict.fromkeys([*runtimes, *packages]):
        if p.exists():
            effect("cleanup.files", lambda: shutil.rmtree(path(str(p))), {"path": str(p)})
    # App pointers and every superseded successful Job agree in one transaction.
    # Original failure events remain immutable diagnostic evidence.
    installed["older"] = []
    if previous:
        installed["previous"] = None
    with manager.journal.transaction() as db:
        manager.journal.put("managed_app", installed["application_id"], installed, db)
        jobs = db.execute(
            "SELECT id,payload FROM records WHERE kind='managed_job' AND json_extract(payload,'$.application_id')=? AND json_extract(payload,'$.phase')='succeeded'",
            (installed["application_id"],),
        ).fetchall()
        for identity, raw in jobs:
            job = loads(raw)
            if job.get("cleanup_pending"):
                job["cleanup_pending"] = False
                job.pop("cleanup_failure", None)
                manager.journal.put("managed_job", identity, job, db)
    manager.journal.flush_export()
    event("cleanup.reconciled", "completed", {"delete_previous": previous})
