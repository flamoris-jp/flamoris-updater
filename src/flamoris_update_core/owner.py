"""Independent application owner; lifecycle drivers remain host-owned."""

import base64
import time
from pathlib import Path
from typing import Callable

from pydantic import Field

from .admission import CURRENT, Admission
from .contracts import OwnerRequest, OwnerResult
from .errors import UpdateError
from .inventory import DeploymentProfile, Observation
from .journal import exclusive, protected_dir
from .models import ID, Manifest, Model
from .postgres import PostgresBinding, PostgresResource
from .resources import TreeBinding, TreeResource, protected_read
from .signing import Key, open_packet, verify
from .wire import decode, digest, dumps, version


class TrustKey(Model):
    id: ID
    domain: ID
    purpose: str
    public_base64: str

    def key(self):
        raw = base64.b64decode(self.public_base64, validate=True)
        if len(raw) != 32:
            raise UpdateError("invalid_profile")
        return Key(raw, self.domain, self.purpose)


class OwnerConfiguration(Model):
    profile: DeploymentProfile
    state_directory: str
    snapshot_directory: str
    trees: list[TreeBinding] = Field(max_length=32)
    postgres: list[PostgresBinding] = Field(max_length=8)
    release_files: list[str] = Field(min_length=1, max_length=128)
    trust_keys: list[TrustKey] = Field(min_length=1, max_length=128)
    domain_configuration: dict


class DomainState(Model):
    schemas: dict[str, str]
    active_work: bool
    unknown_work: bool
    configuration_digest: str | None = None


class ApplicationOwner:
    def __init__(
        self,
        config: OwnerConfiguration,
        application_id: str,
        entry_release: str,
        inspect_domain: Callable[..., DomainState],
        quiesce: Callable[[OwnerConfiguration], None] | None = None,
    ) -> None:
        self.config, self.profile = config, config.profile
        if self.profile.application_id != application_id or self.profile.role != "application":
            raise UpdateError("invalid_profile")
        self.entry_release, self.inspect_domain, self.quiesce = (
            entry_release,
            inspect_domain,
            quiesce,
        )
        self.gate = Admission(Path(config.state_directory))
        self.journal = self.gate.journal
        self.snapshots = Path(config.snapshot_directory)
        protected_dir(self.snapshots)
        self.resources = {b.id: TreeResource(b) for b in config.trees}
        self.resources.update({b.id: PostgresResource(b) for b in config.postgres})
        if set(self.resources) != set(self.profile.resources) or len(self.resources) != len(
            config.trees
        ) + len(config.postgres):
            raise UpdateError("invalid_profile")
        # State/backups must never be inside a backed-up application tree.
        for resource in self.resources.values():
            if isinstance(resource, TreeResource):
                if any(
                    path == resource.root or resource.root in path.parents
                    for path in (self.journal.directory.resolve(), self.snapshots.resolve())
                ):
                    raise UpdateError("invalid_profile")
        self.keys = {k.id: k.key() for k in config.trust_keys}
        if len(self.keys) != len(config.trust_keys):
            raise UpdateError("invalid_profile")
        self.manifests = {}
        for filename in config.release_files:
            raw = protected_read(Path(filename))
            manifest = decode(Manifest, raw)
            verify(
                raw, protected_read(Path(filename + ".sig")), self.keys, application_id, "release"
            )
            selected = manifest.select(self.profile.platform, self.profile.artifact_kind)
            if selected.artifact.digest in self.manifests:
                raise UpdateError("invalid_profile")
            self.manifests[selected.artifact.digest] = (digest(raw), selected)
        self.revision = digest(dumps(config))

    def domain(self):
        result = self.inspect_domain(self.config, self.resources)
        if not isinstance(result, DomainState) or set(result.schemas) != set(self.resources):
            raise UpdateError("domain_invalid")
        return result

    def configuration_revision(self, domain=None):
        domain = self.domain() if domain is None else domain
        return digest(
            dumps(
                {
                    "profile": self.revision,
                    "application": domain.configuration_digest,
                    "credentials": {
                        key: digest(protected_read(Path(resource.binding.dsn_file), private=True))
                        for key, resource in self.resources.items()
                        if isinstance(resource, PostgresResource)
                    },
                }
            )
        )

    def inspect(self, nonce: str):
        domain, gate = self.domain(), self.gate.state()
        installed = self.journal.get("application_installation", self.profile.id)
        with self.journal.connection() as db:
            rows = db.execute("SELECT payload FROM records WHERE kind='owner_operation'").fetchall()
        from .wire import loads

        unresolved = any(loads(row[0])["result"] is None for row in rows)
        return Observation(
            deployment_id=self.profile.id,
            application_id=self.profile.application_id,
            manifest_digest=None if installed is None else installed["manifest_digest"],
            release=None if installed is None else installed["release"],
            schemas=domain.schemas,
            resource_bindings=self.profile.resources,
            physical_binding_digests={
                self.profile.resources[k]: r.binding_digest() for k, r in self.resources.items()
            },
            observed_at=int(time.time()),
            observation_id=nonce,
            profile_digest=digest(dumps(self.profile)),
            config_revision=self.configuration_revision(domain),
            journal_revision=gate["epoch"],
            active_work=domain.active_work or gate["active_work"],
            unknown_work=domain.unknown_work or gate["unknown_work"] or unresolved,
            evidence=["owner-observation-" + str(int(time.time()))],
            absent_resources=[],
            entry_evidence=None if installed is None else installed["entry_evidence"],
            maintenance_epoch=gate["epoch"],
        )

    def _job(self, request):
        job = self.journal.get("application_job", request.job_id)
        claim = self.journal.get("application_claim", self.profile.id)
        if (
            job is None
            or claim is None
            or claim["job_id"] != request.job_id
            or claim["plan_digest"] != request.plan_digest
            or job["plan_digest"] != request.plan_digest
            or job["artifact_digest"] != request.artifact_digest
            or job["config_revision"] != self.configuration_revision()
            or job["physical_bindings"]
            != {k: r.binding_digest() for k, r in self.resources.items()}
        ):
            raise UpdateError("forbidden")
        return job

    def _fenced(self, request):
        state = self.gate.state()
        epochs = {r: state["epoch"] for r in self.profile.resources.values()}
        if (
            not state["closed"]
            or state["job_id"] != request.job_id
            or state["active_work"]
            or (request.maintenance_epochs and request.maintenance_epochs != epochs)
        ):
            raise UpdateError("busy")
        domain = self.domain()
        if domain.active_work or domain.unknown_work:
            raise UpdateError("busy")
        for resource in self.resources.values():
            if isinstance(resource, PostgresResource):
                resource.assert_fenced()
        return epochs

    def perform(self, request: OwnerRequest):
        profile = self.profile
        if (
            request.application_id != profile.application_id
            or request.deployment_id != profile.id
            or (set(request.resource_ids) != set(profile.resources.values()))
            or request.operation not in profile.operations
        ):
            raise UpdateError("forbidden")
        if request.artifact_digest not in self.manifests:
            raise UpdateError("untrusted_release")
        binding = digest(dumps(request))
        with exclusive(self.journal.directory / "owner-operation.lock"):
            previous = self.journal.get("owner_operation", request.operation_id)
            if previous:
                if previous["binding"] != binding:
                    raise UpdateError("operation_conflict")
                if previous["result"] is None:
                    raise UpdateError("outcome_unknown")
                return decode(OwnerResult, dumps(previous["result"]))
            claim = self.journal.get("application_claim", profile.id)
            if claim and (
                claim["job_id"] != request.job_id or claim["plan_digest"] != request.plan_digest
            ):
                raise UpdateError("maintenance_conflict")
            with self.journal.connection() as db:
                rows = db.execute(
                    "SELECT payload FROM records WHERE kind='owner_operation'"
                ).fetchall()
            from .wire import loads

            if any(loads(row[0])["result"] is None for row in rows):
                raise UpdateError("recovery_required")
            # Read-only operations are also bounded by one immutable request.
            with self.journal.transaction() as db:
                self.journal.put(
                    "owner_operation",
                    request.operation_id,
                    {"binding": binding, "result": None},
                    db,
                )
                self.journal.event(db, "owner_intent", request.operation_id)
            self.journal.flush_export()
            result = self._perform(request)
            with self.journal.transaction() as db:
                self.journal.put(
                    "owner_operation",
                    request.operation_id,
                    {"binding": binding, "result": result.model_dump()},
                    db,
                )
                self.journal.event(db, "owner_result", request.operation_id, result.outcome)
            self.journal.flush_export()
            return result

    def _perform(self, request):
        r = request
        root_digest, manifest = self.manifests[r.artifact_digest]
        proofs, snapshot_digest = {}, None
        epoch = self.gate.state()["epoch"]
        epochs = (
            {} if epoch == 0 else {identity: epoch for identity in self.profile.resources.values()}
        )
        domain = self.domain()
        if (
            version(manifest.release) < version(self.entry_release)
            or manifest.migrations
            or manifest.initialization.supported
        ):
            raise UpdateError("unsupported_migration")
        if domain.schemas != manifest.schema_targets:
            raise UpdateError(
                "unsupported_migration", "Use the application's explicit legacy schema procedure"
            )
        if r.operation == "prepare":
            for resource in self.resources.values():
                if isinstance(resource, PostgresResource):
                    resource.restore_preflight()
        elif r.operation == "begin":
            if self.gate.state()["closed"] and self.gate.state()["job_id"] not in {None, r.job_id}:
                raise UpdateError("maintenance_conflict")
            with self.journal.transaction() as db:
                self.journal.put(
                    "application_claim",
                    self.profile.id,
                    {"job_id": r.job_id, "plan_digest": r.plan_digest},
                    db,
                )
                self.journal.put(
                    "application_job",
                    r.job_id,
                    {
                        "plan_digest": r.plan_digest,
                        "artifact_digest": r.artifact_digest,
                        "config_revision": self.configuration_revision(domain),
                        "entry": r.arguments.get("standalone_transition") is True,
                        "physical_bindings": {
                            k: resource.binding_digest() for k, resource in self.resources.items()
                        },
                    },
                    db,
                )
        elif r.operation == "close_admission":
            self._job(r)
            epoch = self.gate.close(r.job_id)
            epochs = {identity: epoch for identity in self.profile.resources.values()}
            proofs = {"admission_closed": True, "durable_maintenance": True}
        elif r.operation == "drain":
            self._job(r)
            gate = self.gate.state()
            if not gate["closed"] or gate["job_id"] != r.job_id or gate["active_work"]:
                raise UpdateError("busy")
            if self.quiesce:
                token = CURRENT.set("owner-maintenance")
                try:
                    self.quiesce(self.config)
                finally:
                    CURRENT.reset(token)
            for key, resource in self.resources.items():
                if isinstance(resource, PostgresResource):
                    with self.journal.transaction() as db:
                        self.journal.put(
                            "login_roles",
                            r.job_id + "." + key,
                            {"roles": resource.login_roles()},
                            db,
                        )
                    resource.fence()
            epochs = self._fenced(r)
            proofs = {"work_drained": True, "unknown_work_absent": True, "writers_fenced": True}
        elif r.operation == "stop":
            self._job(r)
            epochs = self._fenced(r)
            proofs = {
                "writers_fenced": True,
                "maintenance_startup": self.profile.maintenance_startup,
            }
        elif r.operation == "snapshot":
            self._job(r)
            epochs = self._fenced(r)
            path = self.snapshots / r.job_id
            path.mkdir(mode=0o700)
            members = {
                key: resource.snapshot(path / key) for key, resource in self.resources.items()
            }
            fingerprints = {
                key: (
                    resource.fingerprint()
                    if isinstance(resource, PostgresResource)
                    else digest(dumps(resource.inventory()))
                )
                for key, resource in self.resources.items()
            }
            snapshot_digest = digest(
                dumps(
                    {
                        "job_id": r.job_id,
                        "plan_digest": r.plan_digest,
                        "members": members,
                        "fingerprints": fingerprints,
                        "permissions": {
                            key: resource.fingerprint(include_data=False)
                            for key, resource in self.resources.items()
                            if isinstance(resource, PostgresResource)
                        },
                    }
                )
            )
            with self.journal.transaction() as db:
                self.journal.put(
                    "application_snapshot",
                    r.job_id,
                    {
                        "digest": snapshot_digest,
                        "members": members,
                        "fingerprints": fingerprints,
                        "permissions": {
                            key: resource.fingerprint(include_data=False)
                            for key, resource in self.resources.items()
                            if isinstance(resource, PostgresResource)
                        },
                        "verified": False,
                    },
                    db,
                )
            proofs = {"writers_fenced": True, "snapshot_consistent": True}
        elif r.operation == "restore_verify":
            self._job(r)
            epochs = self._fenced(r)
            snapshot = self.journal.get("application_snapshot", r.job_id)
            if snapshot is None:
                raise UpdateError("backup_unverified")
            for key, resource in self.resources.items():
                resource.restore_verify(self.snapshots / r.job_id / key, snapshot["members"][key])
            snapshot_digest = snapshot["digest"]
            with self.journal.transaction() as db:
                self.journal.put(
                    "application_snapshot", r.job_id, {**snapshot, "verified": True}, db
                )
            proofs = {
                "isolated_restore": True,
                "no_production_credentials": True,
                "no_external_effects": True,
                "permissions_preserved": True,
                "domain_valid": True,
            }
        elif r.operation == "activate":
            job = self._job(r)
            epochs = self._fenced(r)
            self._verify_snapshot(r)
            attestation = open_packet(
                r.arguments.get("host_activation"), self.keys, self.profile.host_id, "receipt"
            )
            expected = {
                "kind": "host_activation",
                "application_id": r.application_id,
                "deployment_id": r.deployment_id,
                "artifact_digest": r.artifact_digest,
                "manifest_digest": root_digest,
                "operation_id": r.operation_id,
                "job_id": r.job_id,
                "plan_digest": r.plan_digest,
            }
            boot = self.journal.get("application_boot", r.application_id)
            if (
                attestation != expected
                or boot is None
                or boot["release"] != manifest.release
                or (boot["epoch"] != self.gate.state()["epoch"] or boot["job_id"] != r.job_id)
            ):
                raise UpdateError("outcome_unknown")
            with self.journal.transaction() as db:
                self.journal.put(
                    "application_installation",
                    self.profile.id,
                    {
                        "manifest_digest": root_digest,
                        "release": manifest.release,
                        "entry_evidence": "standalone_transition"
                        if job["entry"]
                        else "verified_adoption",
                        "attestation": attestation,
                        "snapshot_job": r.job_id,
                    },
                    db,
                )
            proofs = {"artifact_verified": True, "maintenance_startup": True}
        elif r.operation == "validate":
            if r.expected_schemas != domain.schemas:
                raise UpdateError("domain_invalid")
            installed = self.journal.get("application_installation", self.profile.id)
            if installed is None or installed["manifest_digest"] != root_digest:
                raise UpdateError("entry_required")
            if r.arguments.get("read_only") is not True:
                self._fenced(r)
                self._verify_snapshot(r)
            else:
                snapshot = self.journal.get("application_snapshot", installed["snapshot_job"])
                if snapshot is None or not snapshot["verified"]:
                    raise UpdateError("backup_unverified")
                for key, resource in self.resources.items():
                    if (
                        isinstance(resource, PostgresResource)
                        and resource.fingerprint(include_data=False) != snapshot["permissions"][key]
                    ):
                        raise UpdateError("domain_invalid")
            proofs = {"domain_valid": True, "permissions_preserved": True}
        elif r.operation == "reopen_admission":
            self._job(r)
            epochs = self._fenced(r)
            self._verify_snapshot(r)
            installed = self.journal.get("application_installation", self.profile.id)
            if installed is None or installed["manifest_digest"] != root_digest:
                raise UpdateError("entry_required")
            for key, resource in self.resources.items():
                if isinstance(resource, PostgresResource):
                    roles = self.journal.get("login_roles", r.job_id + "." + key)
                    resource.reopen(roles["roles"])
            self.gate.open(r.job_id, self.gate.state()["epoch"])
            proofs = {"admission_open": True, "accepted_work_reconciled": True}
        elif r.operation == "release":
            if r.arguments.get("read_only") is not True:
                self._job(r)
            gate = self.gate.state()
            if (
                gate["closed"]
                or gate["unknown_work"]
                or (
                    r.arguments.get("read_only") is not True
                    and (gate["job_id"] != r.job_id or r.maintenance_epochs != epochs)
                )
            ):
                raise UpdateError("recovery_required")
            if r.arguments.get("read_only") is not True:
                with self.journal.transaction() as db:
                    db.execute(
                        "DELETE FROM records WHERE kind='application_claim' AND id=?",
                        (self.profile.id,),
                    )
            proofs = {"safe_lifecycle": True, "release_safe": True}
        else:
            raise UpdateError("unsupported_migration")
        return OwnerResult(
            contract_version=1,
            operation=r.operation,
            application_id=r.application_id,
            deployment_id=r.deployment_id,
            artifact_digest=r.artifact_digest,
            operation_id=r.operation_id,
            outcome="verified",
            schemas=self.domain().schemas,
            evidence=[r.operation_id],
            maintenance_epochs=epochs,
            proofs=proofs,
            snapshot_digest=snapshot_digest,
        )

    def _verify_snapshot(self, request):
        snapshot = self.journal.get("application_snapshot", request.job_id)
        if snapshot is None or not snapshot["verified"]:
            raise UpdateError("backup_unverified")
        for key, resource in self.resources.items():
            actual = (
                resource.fingerprint()
                if isinstance(resource, PostgresResource)
                else digest(dumps(resource.inventory()))
            )
            if actual != snapshot["fingerprints"][key]:
                raise UpdateError("resource_changed")
