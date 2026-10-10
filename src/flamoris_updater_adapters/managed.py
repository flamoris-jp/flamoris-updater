"""Per-application install/update jobs over the same protected local execution path.

Recipes are release-maintainer artifacts. Operators supply settings, never shell
commands, unit contents or arbitrary file destinations through Web/MCP/CLI.
"""

import hashlib
import os
import platform
import secrets
import shutil
import socket
import threading
import time
from itertools import chain
from pathlib import Path
from string import Template
from typing import Literal
from urllib.parse import urlsplit

import httpx
from pydantic import Field, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Digest, Model, VersionRange
from flamoris_update_core.wire import decode, digest, dumps, loads, version

from .artifacts import Fetcher, origin
from .diagnostics import (
    LayoutRequest,
    Log,
    LogPage,
    describe,
    event,
    failure,
    recording,
    redact,
    save_layout,
)
from .diagnostics import effect as recorded_effect
from .install import (
    VERSIONS,
    Configuration,
    DockerApplication,
    File,
    Installer,
    NativeApplication,
    path,
)
from .journal import Journal, durable_write, exclusive
from .self_update import SELF, SelfRelease, SelfStart

MANAGED_TARGETS = [*VERSIONS, SELF]


def https(value):
    u = urlsplit(value)
    if u.scheme != "https" or not u.hostname or u.username or u.password or u.fragment:
        raise UpdateError("untrusted_origin")
    return value


class Setting(Model):
    key: str = Field(pattern=r"^[A-Z][A-Z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=128)
    default: str = Field(default="", max_length=4096)
    secret: bool = False
    required: bool = False
    generate: bool = False
    kind: Literal["text", "port", "name", "url_password"] = "text"

    @model_validator(mode="after")
    def private_default(self):
        if (self.secret and self.default) or (self.generate and not self.secret):
            raise ValueError("Release recipes cannot distribute credentials")
        return self


class Download(Model):
    url: str
    digest: Digest


class Recipe(Model):
    application_id: ID
    release: str
    platform: Literal["linux/amd64", "linux/arm64"]
    compatible_from: list[str] = Field(default_factory=list, max_length=128)
    dependencies: dict[ID, VersionRange] = Field(default_factory=dict, max_length=6)
    settings: list[Setting] = Field(default_factory=list, max_length=128)
    downloads: dict[str, Download] = Field(default_factory=dict, max_length=256)
    generated: dict[str, str] = Field(default_factory=dict, max_length=128)
    application: dict

    @model_validator(mode="after")
    def identity(self):
        if self.application_id not in VERSIONS or version(self.release) < version(
            VERSIONS[self.application_id]
        ):
            raise ValueError("Unsupported application or initial release")
        if len({s.key for s in self.settings}) != len(self.settings):
            raise ValueError("Duplicate setting")
        for name in [*self.downloads, *self.generated]:
            if (
                not name
                or Path(name).is_absolute()
                or ".." in Path(name).parts
                or any(c in name for c in "\r\n\0")
            ):
                raise ValueError("Package members must be relative")
        if set(self.downloads) & set(self.generated):
            raise ValueError("Package and settings inputs must be separate")
        for item in self.downloads.values():
            https(item.url)
        for release in self.compatible_from:
            version(release)
        return self


class Catalog(Model):
    catalog_version: Literal[1]
    recipes: list[Recipe] = Field(max_length=128)
    updater_releases: list[SelfRelease] = Field(default_factory=list, max_length=128)

    @model_validator(mode="after")
    def unique(self):
        identities = [(r.application_id, r.release, r.platform) for r in self.recipes]
        if len(set(identities)) != len(identities):
            raise ValueError("Duplicate release")
        self_ids = [(r.release, r.artifact.platform) for r in self.updater_releases]
        if len(set(self_ids)) != len(self_ids):
            raise ValueError("Duplicate Updater release")
        return self


class Start(Model):
    application_id: ID
    release: str
    request_key: str = Field(min_length=1, max_length=128)
    settings: dict[str, str] = Field(default_factory=dict, max_length=128)


class Target(Model):
    application_id: ID


class Job(Model):
    job_id: ID


class Refresh(Model):
    refresh: bool = False


MANAGED_TOOLS = {
    "updater_managed_log_get": (
        LogPage,
        "Paged, secret-free effect timeline for one application Job",
        "read",
    ),
    "updater_managed_layout_get": (
        LayoutRequest,
        "Recorded installation and candidate placement for documentation",
        "read",
    ),
    "updater_self_status": (Model, "Updater version and compatible self-update releases", "read"),
    "updater_self_update": (
        SelfStart,
        "Update Web and manager through the stable supervisor",
        "execute",
    ),
    "updater_apps_list": (Refresh, "Installed apps, available recipes and settings", "read"),
    "updater_install": (Start, "Install one selected application", "execute"),
    "updater_update": (
        Start,
        "Stage beside current, retain settings, switch and verify",
        "execute",
    ),
    "updater_install_complete": (Target, "Verify application after its initial setup", "execute"),
    "updater_install_start": (
        Target,
        "Start the staged application for its initial setup",
        "execute",
    ),
    "updater_previous_delete": (Target, "Delete retained previous executables only", "execute"),
    "updater_managed_job_get": (Job, "Shared durable install/update status", "read"),
    "updater_managed_history": (Model, "Shared durable job history", "read"),
}


class Manager:
    def __init__(self, state, root, *, installer=Installer, client=None, self_configuration=None):
        self.state, self.root = path(str(state)), path(str(root))
        self.journal = Journal(self.state)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o755)
        self.installer = installer
        self.self_configuration = self_configuration
        if (
            self_configuration
            and self_configuration.bootstrap_executable
            and not self.journal.get("self_installation", "current")
        ):
            from .self_update import initial_record

            with self.journal.transaction() as db:
                self.journal.put(
                    "self_installation", "current", initial_record(self_configuration), db
                )
        self.client = client or httpx.Client(
            verify=True, trust_env=False, follow_redirects=False, timeout=60
        )
        self.stopping, self.wakeup = threading.Event(), threading.Event()

    def configure(self, source):
        https(source)
        with exclusive(self.state / "manager.lock"):
            if self.journal.get("manager_config", "source"):
                raise UpdateError("already_installed")
            catalog = decode(Catalog, self._download(source, 1024 * 1024))
            self.accept_catalog(catalog)
            with self.journal.transaction() as db:
                self.journal.put("manager_config", "source", {"url": source}, db)
                self.journal.put("manager_catalog", "current", catalog.model_dump(), db)
            return {"configured": True}

    def _download(self, url, limit, destination=None, expected=None):
        https(url)
        h, parts = hashlib.sha256(), []
        fetcher = Fetcher([origin(url)], self.client, public_redirects=True)
        chunks = fetcher.chunks(url, limit)
        try:
            first = next(chunks, None)
            with destination.open("xb") if destination else _Memory() as stream:
                for chunk in chain(() if first is None else (first,), chunks):
                    h.update(chunk)
                    if destination:
                        stream.write(chunk)
                    else:
                        parts.append(chunk)
                if destination:
                    stream.flush()
                    os.fsync(stream.fileno())
        finally:
            chunks.close()
        if expected and "sha256:" + h.hexdigest() != expected:
            raise UpdateError("artifact_mismatch")
        return b"".join(parts)

    def catalog(self, refresh=False):
        config = self.journal.get("manager_config", "source")
        if not config:
            return Catalog(catalog_version=1, recipes=[])
        if refresh:
            catalog = decode(Catalog, self._download(config["url"], 1024 * 1024))
            self.accept_catalog(catalog)
            return catalog
        raw = self.journal.get("manager_catalog", "current")
        return decode(Catalog, dumps({k: v for k, v in raw.items() if k != "_revision"}))

    def accept_catalog(self, catalog):
        with self.journal.transaction() as db:
            for recipe in [*catalog.recipes, *catalog.updater_releases]:
                identity = digest(
                    dumps(
                        {
                            "application_id": recipe.application_id
                            if isinstance(recipe, Recipe)
                            else SELF,
                            "release": recipe.release,
                            "platform": recipe.platform
                            if isinstance(recipe, Recipe)
                            else recipe.artifact.platform,
                        }
                    )
                )
                binding = digest(dumps(recipe))
                previous = self.journal.get("catalog_recipe", identity, db)
                if previous and previous["digest"] != binding:
                    raise UpdateError("operation_conflict", "Published releases must be immutable")
                self.journal.put("catalog_recipe", identity, {"digest": binding}, db)
            self.journal.put("manager_catalog", "current", catalog.model_dump(), db)

    def invoke(self, name, payload):
        if name not in MANAGED_TOOLS:
            raise UpdateError("invalid_input")
        args = decode(MANAGED_TOOLS[name][0], dumps(payload))
        if name in {"updater_managed_log_get", "updater_managed_layout_get"}:
            if args.application_id not in MANAGED_TARGETS:
                raise UpdateError("invalid_input")
            if args.job_id:
                job = self.journal.get("managed_job", args.job_id)
                if not job or job["application_id"] != args.application_id:
                    raise UpdateError("invalid_input")
            if name == "updater_managed_log_get":
                return {"job": job, **Log(self.journal, args.job_id).page(args.after, args.limit)}
            return self.layout(args.application_id, args.job_id)
        if MANAGED_TOOLS[name][2] == "execute" and name != "updater_self_update":
            with self.journal.connection() as db:
                if db.execute(
                    "SELECT 1 FROM records WHERE kind='managed_job' AND json_extract(payload,'$.action')='self_update' AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') LIMIT 1"
                ).fetchone():
                    raise UpdateError("busy")
        if name == "updater_self_status":
            return {
                "installation": self.journal.get("self_installation", "current"),
                "supported": bool(
                    self.self_configuration and self.self_configuration.bootstrap_executable
                ),
                "releases": [
                    {"release": r.release, "compatible_from": r.compatible_from}
                    for r in self.catalog().updater_releases
                    if r.artifact.platform == self.hardware()
                ],
            }
        if name == "updater_self_update":
            from .self_update import admit

            return admit(self, args)
        if name == "updater_apps_list":
            catalog = self.catalog(refresh=args.refresh)
            return {
                "root": str(self.root),
                "items": [
                    {
                        "application_id": a,
                        "installation": self.journal.get("managed_app", a),
                        "releases": [
                            {
                                "release": r.release,
                                "compatible_from": r.compatible_from,
                                "settings": [s.model_dump() for s in r.settings],
                                "dependencies": {
                                    k: v.model_dump() for k, v in r.dependencies.items()
                                },
                            }
                            for r in catalog.recipes
                            if r.application_id == a and r.platform == self.hardware()
                        ],
                    }
                    for a in VERSIONS
                ],
            }
        if name == "updater_managed_history":
            with self.journal.connection() as db:
                return {
                    "items": [
                        loads(row[0])
                        for row in db.execute(
                            "SELECT payload FROM records WHERE kind='managed_job' ORDER BY json_extract(payload,'$.created_at') DESC,id DESC LIMIT 100"
                        )
                    ]
                }
        if name == "updater_managed_job_get":
            record = self.journal.get("managed_job", args.job_id)
            if not record:
                raise UpdateError("invalid_input")
            return record
        if name in {"updater_install", "updater_update"}:
            return self.start("install" if name.endswith("install") else "update", args)
        if name == "updater_install_complete":
            return self.complete(args.application_id)
        if name == "updater_install_start":
            return self.start_setup(args.application_id)
        return self.delete_previous(args.application_id)

    @staticmethod
    def hardware():
        return {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())

    def start(self, action, args):
        recipe = next(
            (
                r
                for r in self.catalog().recipes
                if (r.application_id, r.release, r.platform)
                == (args.application_id, args.release, self.hardware())
            ),
            None,
        )
        if not recipe:
            raise UpdateError("release_unavailable")
        binding = digest(
            dumps({"action": action, "arguments": args.model_dump(), "recipe": recipe.model_dump()})
        )
        key = digest(dumps({"application": args.application_id, "key": args.request_key}))
        with exclusive(self.state / "manager.lock"), self.journal.transaction() as db:
            previous = self.journal.get("managed_request", key, db)
            if previous:
                if previous["binding"] != binding:
                    raise UpdateError("idempotency_conflict")
                return self.journal.get("managed_job", previous["job_id"], db)
            installed = self.journal.get("managed_app", args.application_id, db)
            if (
                action == "install"
                and installed
                or action == "update"
                and (not installed or installed["phase"] != "succeeded")
            ):
                raise UpdateError("already_installed" if action == "install" else "not_installed")
            if action == "update" and (
                args.settings
                or version(args.release) <= version(installed["release"])
                or installed["release"] not in recipe.compatible_from
            ):
                raise UpdateError(
                    "unsupported_migration",
                    "Update must preserve settings and declare compatibility with the current release",
                )
            for provider, accepted in recipe.dependencies.items():
                item = self.journal.get("managed_app", provider, db)
                if (
                    not item
                    or item["phase"] != "succeeded"
                    or not accepted.accepts(item["release"])
                ):
                    raise UpdateError(
                        "incompatible_dependency", "Install the declared provider first"
                    )
            if action == "update":
                for consumer in self.journal.list("managed_app"):
                    if consumer["application_id"] == args.application_id:
                        continue
                    bound = self.journal.get("managed_recipe", consumer["job_id"], db)
                    requirement = bound["dependencies"].get(args.application_id) if bound else None
                    if requirement and not VersionRange.model_validate(requirement).accepts(
                        args.release
                    ):
                        raise UpdateError(
                            "incompatible_dependency",
                            "An installed consumer cannot use the new provider release",
                        )
            # One active local job also prevents dependency updates and cleanup racing cutover.
            if db.execute(
                "SELECT 1 FROM records WHERE kind='managed_job' AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') LIMIT 1"
            ).fetchone():
                raise UpdateError("busy")
            identity = "job-" + secrets.token_hex(16)
            settings = {
                s.key: args.settings.get(s.key, s.default)
                or (secrets.token_urlsafe(32) if s.generate else "")
                for s in recipe.settings
            }
            if action == "install" and (
                set(args.settings) - set(settings)
                or any(
                    (s.required and not settings[s.key])
                    or any(c in settings[s.key] for c in "\r\n\0")
                    or len(settings[s.key]) > 4096
                    for s in recipe.settings
                )
            ):
                raise UpdateError("invalid_input")
            import re

            for setting in recipe.settings if action == "install" else []:
                value = settings[setting.key]
                if (
                    (
                        setting.kind == "port"
                        and (not value.isdecimal() or not 1 <= int(value) <= 65535)
                    )
                    or (
                        setting.kind == "name" and not re.fullmatch(r"[a-z][a-z0-9_-]{0,62}", value)
                    )
                    or (
                        setting.kind == "url_password"
                        and not re.fullmatch(r"[a-zA-Z0-9_-]{16,128}", value)
                    )
                ):
                    raise UpdateError("invalid_input", "Setting does not match its declared format")
            if action == "install":
                target = self.state / "settings" / args.application_id
                target.mkdir(parents=True, exist_ok=True, mode=0o700)
                durable_write(target / "values.json", dumps(settings))
            job = {
                "job_id": identity,
                "application_id": args.application_id,
                "release": args.release,
                "action": action,
                "phase": "accepted",
                "step": None,
                "recipe": digest(dumps(recipe)),
                "created_at": int(time.time()),
                "from_release": installed["release"] if installed else None,
                "host": socket.gethostname(),
                "platform": self.hardware(),
            }
            self.journal.put("managed_recipe", identity, recipe.model_dump(), db)
            self.journal.put("managed_job", identity, job, db)
            self.journal.put("managed_request", key, {"binding": binding, "job_id": identity}, db)
            self.journal.event(db, "managed_job", identity, "accepted")
        self.wakeup.set()
        return job

    def _profile(self, recipe, identity):
        package = self.state / "packages" / identity
        package.mkdir(parents=True, mode=0o700)
        settings = loads(
            (self.state / "settings" / recipe.application_id / "values.json").read_bytes()
        )
        values = {
            **settings,
            "root": str(self.root / recipe.application_id),
            "package": str(package),
            "release": recipe.release,
        }
        for name, item in recipe.downloads.items():
            destination = package / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            recorded_effect(
                "artifact.download",
                lambda: self._download(item.url, 4 * 1024**3, destination, item.digest),
                {"member": name, "digest": item.digest, "destination": str(destination)},
            )
        for name, template in recipe.generated.items():
            destination = package / name
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            try:
                recorded_effect(
                    "configuration.generate",
                    lambda: durable_write(
                        destination, Template(template).substitute(values).encode()
                    ),
                    {"path": str(destination), "private": True},
                )
            except (ValueError, KeyError):
                raise UpdateError("invalid_profile") from None

        def render(obj):
            if isinstance(obj, str):
                return Template(obj).substitute(values)
            if isinstance(obj, list):
                return [render(v) for v in obj]
            if isinstance(obj, dict):
                if set(obj) == {"setting_int"}:
                    key = obj["setting_int"]
                    if not any(s.key == key and s.kind == "port" for s in recipe.settings):
                        raise UpdateError("invalid_profile")
                    return int(settings[key])
                out = {k: render(v) for k, v in obj.items()}
                if set(out) == {"path", "digest"} or set(out) == {"path", "digest", "private"}:
                    candidate = Path(out["path"])
                    if not candidate.is_relative_to(package):
                        raise UpdateError("unsafe_storage")
                    if (
                        out["digest"] == "generated"
                        and candidate.relative_to(package).as_posix() not in recipe.generated
                    ):
                        raise UpdateError(
                            "invalid_profile", "Only generated settings receive a local digest"
                        )
                    out["digest"] = (
                        digest(candidate.read_bytes())
                        if out["digest"] == "generated"
                        else out["digest"]
                    )
                return out
            return obj

        app = render(recipe.application)
        if (app.get("application_id"), app.get("release")) != (
            recipe.application_id,
            recipe.release,
        ):
            raise UpdateError("artifact_mismatch")
        cfg = decode(
            Configuration,
            dumps(
                {
                    "install_profile_version": 1,
                    "expected_hostname": socket.gethostname(),
                    "platform": recipe.platform,
                    "state_directory": str(self.state / "installer"),
                    "applications": [app],
                }
            ),
        )
        instance = cfg.applications[0]
        app_root = self.root / recipe.application_id
        for value in [
            *(d.path for d in instance.directories),
            *(f.destination for f in instance.files),
            *([instance.venv] if isinstance(instance, NativeApplication) else []),
        ]:
            candidate = Path(value)
            if not candidate.is_relative_to(app_root) or ".." in candidate.parts:
                raise UpdateError("unsafe_storage")
            # Runtime-owned data roots may exist on update. Their parent namespace
            # stays administrator-owned; no symlink can redirect management writes.
            path(str(app_root))
            if any(
                p.is_symlink()
                for p in [candidate, *candidate.parents]
                if p.is_relative_to(app_root)
            ):
                raise UpdateError("unsafe_storage")
        if isinstance(instance, DockerApplication):
            if not instance.container_name.startswith(recipe.application_id):
                raise UpdateError("invalid_profile")
        else:
            if Path(instance.venv) != app_root / "releases" / recipe.release:
                raise UpdateError(
                    "invalid_profile", "Native releases must use immutable per-version directories"
                )
            if any(not u.name.startswith(recipe.application_id + ".") for u in instance.units):
                raise UpdateError("invalid_profile")
        return cfg

    def persist(self, kind, identity, record):
        with self.journal.transaction() as db:
            self.journal.put(kind, identity, record, db)
            self.journal.event(db, kind, identity, record.get("phase", ""))
        self.journal.flush_export()
        if kind == "managed_job":
            event(
                "job.state",
                record.get("phase", ""),
                {"step": record.get("step"), "error": record.get("error")},
            )

    def secrets(self, identity):
        recipe = self.journal.get("managed_recipe", identity)
        if not recipe:
            return []
        values = loads(
            (self.state / "settings" / recipe["application_id"] / "values.json").read_bytes()
        )
        return [values.get(s["key"], "") for s in recipe["settings"] if s["secret"]]

    def save_layout(self, identity, app, installer):
        layout = describe(app, self.root / app.application_id, installer.unit_directory)
        layout.update(
            host=socket.gethostname(),
            platform=self.hardware(),
            unit_directory=str(installer.unit_directory),
        )
        installed = self.journal.get("managed_app", app.application_id)
        if installed:
            layout["previous_layout"] = self.layout(app.application_id)["current"]
        save_layout(self.journal, identity, layout)

    def layout(self, application, identity=None):
        with self.journal.connection() as db:
            row = db.execute(
                "SELECT id FROM records WHERE kind='managed_job' AND json_extract(payload,'$.application_id')=? ORDER BY json_extract(payload,'$.created_at') DESC,rowid DESC LIMIT 1",
                (application,),
            ).fetchone()
        selected = identity or (row[0] if row else None)
        candidate = self.journal.get("managed_layout", selected) if selected else None
        installed = self.journal.get("managed_app", application)
        current = None
        if installed:
            bound = self.journal.get("managed_layout", installed["job_id"])
            profile = installed["profile"]
            app = decode(
                NativeApplication if profile["kind"] == "native" else DockerApplication,
                dumps(profile),
            )
            current = redact(
                describe(
                    app,
                    self.root / application,
                    (bound or {}).get("unit_directory", "/etc/systemd/system"),
                ),
                self.secrets(installed["job_id"]),
            )
            current.update(
                installation_phase=installed["phase"],
                job_id=installed["job_id"],
                host=(bound or {}).get("host"),
                recorded_at_ms=(bound or {}).get("recorded_at_ms"),
            )
        if application == SELF:
            from .self_update import deployment_layout

            bound = self.journal.get("self_installation", "current")
            layout_bound = (
                self.journal.get("managed_layout", bound.get("job_id"))
                if bound and bound.get("job_id")
                else None
            )
            current = (
                deployment_layout(
                    self.self_configuration, bound, (layout_bound or {}).get("configuration_file")
                )
                if self.self_configuration and bound
                else bound
            )
        return dict(
            application_id=application,
            current=current,
            candidate=candidate,
            candidate_job=self.journal.get("managed_job", selected) if selected else None,
            previous=(installed or {}).get("previous"),
            older=(installed or {}).get("older", [])[:20],
            older_count=len((installed or {}).get("older", [])),
            evidence="recorded_bindings_and_effects",
            live_state=False,
            diagnostics_directory=str(self.state / "diagnostics"),
        )

    def run_job(self, identity):
        with (
            exclusive(self.state / "manager.lock"),
            recording(self.journal, identity) as log,
        ):
            job = self.journal.get("managed_job", identity)
            if not job or job["action"] == "self_update" or job["phase"] != "accepted":
                return

            def effect(name, fn):
                job.update(phase="intent", step=name)
                self.persist("managed_job", identity, job)
                result = recorded_effect(name, fn)
                job.update(phase="running", step=name)
                self.persist("managed_job", identity, job)
                return result

            try:
                log.secrets.extend(self.secrets(identity))
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
                recipe = decode(
                    Recipe,
                    dumps(
                        {
                            k: v
                            for k, v in self.journal.get("managed_recipe", identity).items()
                            if k != "_revision"
                        }
                    ),
                )
                if digest(dumps(recipe)) != job["recipe"]:
                    raise UpdateError("journal_corrupt")

                cfg = effect("download", lambda: self._profile(recipe, identity))
                installer = self.installer(cfg)
                app = cfg.applications[0]
                if job["action"] == "install":
                    self.save_layout(identity, app, installer)
                    # Application setup/health is explicitly a later step.
                    effect("install", lambda: installer.apply(start=False))
                    installed = {
                        "application_id": app.application_id,
                        "release": app.release,
                        "phase": "awaiting_setup",
                        "profile": app.model_dump(),
                        "previous": None,
                        "older": [],
                        "job_id": identity,
                    }
                    job["phase"] = "awaiting_setup"
                else:
                    installed = self.journal.get("managed_app", app.application_id)
                    old = decode(type(app), dumps(installed["profile"]))
                    # Mutable paths/security/mounts/units remain exactly the recorded installation.
                    if isinstance(app, DockerApplication):
                        changed = {"release", "image_id", "image_archive", "database"}
                        if app.model_dump(exclude=changed | {"files"}) != old.model_dump(
                            exclude=changed | {"files"}
                        ):
                            raise UpdateError(
                                "invalid_profile",
                                "Release attempts to change retained runtime bindings",
                            )
                        app = app.model_copy(update={"files": old.files, "database": old.database})
                    else:
                        if [u.name for u in app.units] != [
                            u.name for u in old.units
                        ] or app.files != old.files:
                            # New input sources can differ; destinations and retained bytes cannot.
                            if [f.destination for f in app.files] != [
                                f.destination for f in old.files
                            ] or [u.name for u in app.units] != [u.name for u in old.units]:
                                raise UpdateError("invalid_profile")
                        # All other native runtime bindings stay pinned too.
                        changed = {"release", "venv", "wheels", "units", "directories", "files"}
                        if app.model_dump(exclude=changed) != old.model_dump(exclude=changed):
                            raise UpdateError("invalid_profile")
                        path(app.venv).parent.mkdir(parents=True, exist_ok=True)
                        app = app.model_copy(update={"files": old.files})
                    # Copies are mutable application settings. Carry their actual
                    # installed bytes rather than keeping old package inputs alive.
                    retained_files = []
                    for copied in app.files:
                        candidate = path(copied.destination)
                        source = File(
                            path=str(candidate),
                            digest=digest(candidate.read_bytes()),
                            private=copied.source.private,
                        )
                        source.verify()
                        retained_files.append(copied.model_copy(update={"source": source}))
                    app = app.model_copy(update={"files": retained_files})
                    self.save_layout(identity, app, installer)
                    effect("verify_current", lambda: installer._verify_running(old))
                    artifact_inputs = (
                        [app.image_archive]
                        if isinstance(app, DockerApplication)
                        else [*app.wheels, *(u.source for u in app.units)]
                    )
                    for f in artifact_inputs:
                        recorded_effect(
                            "artifact.verify", f.verify, {"path": f.path, "digest": f.digest}
                        )
                    effect("stage", lambda: installer._stage(app))
                    retained = self._retained(old, identity)
                    retained["package_id"] = installed["job_id"]
                    job["retained_candidate"] = retained
                    event("runtime.retain_previous", "recorded", retained)
                    effect("stop", lambda: self._stop(installer, old, retained))
                    effect("switch", lambda: installer._start(app))
                    effect("health", lambda: installer.health(app))
                    effect("verify_running", lambda: installer._verify_running(app))
                    if installed["previous"]:
                        installed["older"].append(installed["previous"])
                    installed.update(
                        release=app.release,
                        profile=app.model_dump(),
                        previous=retained,
                        phase="succeeded",
                        job_id=identity,
                    )
                    job["phase"] = "succeeded"
                self.persist("managed_app", app.application_id, installed)
                self.persist("managed_job", identity, job)
                if job["phase"] == "succeeded":
                    try:
                        recorded_effect("cleanup", lambda: self._cleanup(installed, previous=False))
                    except Exception as error:
                        job["cleanup_pending"] = True
                        job["cleanup_failure"] = failure(error)
                        self.persist("managed_job", identity, job)
            except BaseException as error:
                job.update(
                    phase="recovery_required",
                    error=error.code if isinstance(error, UpdateError) else "outcome_unknown",
                    failure=failure(error),
                )
                self.persist("managed_job", identity, job)
                if not isinstance(error, Exception):
                    raise

    def _retained(self, app, identity):
        return (
            {"kind": app.kind, "release": app.release, "path": app.venv}
            if isinstance(app, NativeApplication)
            else {
                "kind": app.kind,
                "release": app.release,
                "container": app.container_name + "-" + identity[4:16],
                "image_id": app.image_id,
            }
        )

    @staticmethod
    def _stop(installer, app, retained):
        if isinstance(app, DockerApplication):
            installer.command(["/usr/bin/docker", "stop", "--time", "30", app.container_name])
            installer.command(
                ["/usr/bin/docker", "rename", app.container_name, retained["container"]]
            )
        else:
            installer.command(["/usr/bin/systemctl", "stop", *[u.name for u in app.units]])

    def complete(self, application):
        with exclusive(self.state / "manager.lock"):
            installed = self.journal.get("managed_app", application)
            if not installed or installed["phase"] != "awaiting_setup":
                raise UpdateError("invalid_input")
            with recording(self.journal, installed["job_id"], self.secrets(installed["job_id"])):
                app = installed["profile"]
                cfg = decode(
                    Configuration,
                    dumps(
                        {
                            "install_profile_version": 1,
                            "expected_hostname": socket.gethostname(),
                            "platform": self.hardware(),
                            "state_directory": str(self.state / "installer"),
                            "applications": [app],
                        }
                    ),
                )
                installer = self.installer(cfg)
                recorded_effect("setup.health", lambda: installer.health(cfg.applications[0]))
                recorded_effect(
                    "setup.verify_running", lambda: installer._verify_running(cfg.applications[0])
                )
                installed["phase"] = "succeeded"
                self.persist("managed_app", application, installed)
                job = self.journal.get("managed_job", installed["job_id"])
                job.update(phase="succeeded", step="initial_setup_verified")
                self.persist("managed_job", job["job_id"], job)
                return {"application_id": application, "phase": "succeeded"}

    def start_setup(self, application):
        with exclusive(self.state / "manager.lock"):
            installed = self.journal.get("managed_app", application)
            if not installed or installed["phase"] != "awaiting_setup":
                raise UpdateError("invalid_input")
            with recording(self.journal, installed["job_id"], self.secrets(installed["job_id"])):
                cfg = decode(
                    Configuration,
                    dumps(
                        {
                            "install_profile_version": 1,
                            "expected_hostname": socket.gethostname(),
                            "platform": self.hardware(),
                            "state_directory": str(self.state / "installer"),
                            "applications": [installed["profile"]],
                        }
                    ),
                )
                app = cfg.applications[0]
                installer = self.installer(cfg)
                if isinstance(app, DockerApplication):
                    installer.command(["/usr/bin/docker", "start", app.container_name])
                else:
                    installer.command(["/usr/bin/systemctl", "start", *[u.name for u in app.units]])
                return {"application_id": application, "phase": "awaiting_setup", "started": True}

    def _cleanup(self, installed, previous):
        current = installed["profile"]
        entries = [
            *installed["older"],
            *([installed["previous"]] if previous and installed["previous"] else []),
        ]
        for entry in entries:
            if entry["kind"] == "native":
                p = path(entry["path"])
                expected = self.root / installed["application_id"] / "releases" / entry["release"]
                if p != expected or str(p) == current.get("venv"):
                    raise UpdateError("unsafe_storage")
                if p.exists():
                    recorded_effect(
                        "cleanup.runtime",
                        lambda: shutil.rmtree(p),
                        {"path": str(p), "release": entry["release"]},
                    )
            else:
                name = entry["container"]
                if not name.startswith(installed["application_id"] + "-") or name == current.get(
                    "container_name"
                ):
                    raise UpdateError("unsafe_storage")
                cfg = decode(
                    Configuration,
                    dumps(
                        {
                            "install_profile_version": 1,
                            "expected_hostname": socket.gethostname(),
                            "platform": self.hardware(),
                            "state_directory": str(self.state / "installer"),
                            "applications": [current],
                        }
                    ),
                )
                command = self.installer(cfg).command
                names = command(
                    ["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"]
                )
                if name in names.decode().splitlines():
                    observed = loads(
                        command(
                            [
                                "/usr/bin/docker",
                                "container",
                                "inspect",
                                "--format",
                                "{{json .}}",
                                name,
                            ]
                        )
                    )
                    if (
                        observed.get("Image") != entry.get("image_id")
                        or observed.get("State", {}).get("Running") is not False
                    ):
                        raise UpdateError("unsafe_storage")
                    command(["/usr/bin/docker", "container", "rm", name])
                if entry.get("image_id") != current.get("image_id"):
                    # No force/prune: Docker keeps images still used by another container.
                    command(["/usr/bin/docker", "image", "rm", entry["image_id"]])
            package_id = entry.get("package_id")
            if package_id:
                import re

                if (
                    not re.fullmatch(r"job-[0-9a-f]{32}", package_id)
                    or package_id == installed["job_id"]
                ):
                    raise UpdateError("unsafe_storage")
                package = path(str(self.state / "packages" / package_id))
                if package.exists():
                    recorded_effect(
                        "cleanup.package", lambda: shutil.rmtree(package), {"path": str(package)}
                    )
        installed["older"] = []
        if previous:
            installed["previous"] = None
        self.persist("managed_app", installed["application_id"], installed)

    def delete_previous(self, application):
        with exclusive(self.state / "manager.lock"):
            with self.journal.connection() as db:
                active = db.execute(
                    "SELECT 1 FROM records WHERE kind='managed_job' AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') LIMIT 1"
                ).fetchone()
            if active:
                raise UpdateError("busy")
            installed = self.journal.get("managed_app", application)
            if not installed or installed["phase"] != "succeeded":
                raise UpdateError("busy")
            with recording(self.journal, installed["job_id"], self.secrets(installed["job_id"])):
                recorded_effect("cleanup.delete_previous", lambda: self._cleanup(installed, True))
                return {"application_id": application, "deleted_previous": True}

    def worker(self):
        # A recorded intent is never automatically replayed after process loss.
        with self.journal.connection() as db:
            interrupted = [
                loads(row[0])
                for row in db.execute(
                    "SELECT payload FROM records WHERE kind='managed_job' AND json_extract(payload,'$.action')!='self_update' AND json_extract(payload,'$.phase') IN ('intent','running')"
                )
            ]
        for job in interrupted:
            job.update(
                phase="recovery_required",
                failure={"error": "outcome_unknown", "kind": "interrupted"},
            )
            with recording(self.journal, job["job_id"], self.secrets(job["job_id"])):
                event("job.interrupted", "unknown", {"step": job.get("step")})
                self.persist("managed_job", job["job_id"], job)
        while not self.stopping.is_set():
            with self.journal.connection() as db:
                pending = db.execute(
                    "SELECT id FROM records WHERE kind='managed_job' AND json_extract(payload,'$.action')!='self_update' AND json_extract(payload,'$.phase')='accepted' LIMIT 1"
                ).fetchone()
            if pending:
                self.run_job(pending[0])
            self.wakeup.wait(1)
            self.wakeup.clear()


class _Memory:
    def __enter__(self):
        return None

    def __exit__(self, *_):
        pass
