import time
from dataclasses import dataclass

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from flamoris_update_core.contracts import PROOFS, OwnerResult
from flamoris_update_core.inventory import DeploymentProfile, Observation, Resource
from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, digest, dumps
from flamoris_updater.coordinator import Coordinator
from flamoris_updater_adapters.authority import Authority
from flamoris_updater_adapters.executor import HostExecutor
from flamoris_updater_adapters.journal import Journal
from flamoris_updater_adapters.releases import ReleaseStore
from flamoris_updater_adapters.signing import Key, Signer


def manifest(
    release="1.0.0",
    schema="db-1",
    migrations=None,
    application="example-app",
    dependencies=None,
    interfaces=None,
):
    human = b"Human release notes"
    changes = dumps(
        {
            "format_version": 1,
            "application_id": application,
            "release": release,
            "entries": [],
            "restart_required": True,
            "recovery_conditions": "Retain evidence",
        }
    )
    raw = dumps(
        {
            "manifest_version": 1,
            "application_id": application,
            "release": release,
            "source": {
                "repository": "example/application",
                "tag": "v" + release,
                "revision": "a" * 40,
            },
            "artifact": {
                "kind": "native",
                "platform": "linux/amd64",
                "locator": "https://releases.example.invalid/app.tar",
                "digest": digest(b"artifact"),
                "max_expanded_bytes": 1024 * 1024,
                "content_index_digest": digest(b"index"),
            },
            "components": [],
            "interfaces": interfaces or [],
            "dependencies": dependencies or [],
            "schema_targets": {"database": schema},
            "migrations": migrations or [],
            "lifecycle_profile": {
                "id": "lifecycle",
                "restart_required": True,
                "admission_gate_required": True,
                "validation_profiles": ["domain"],
            },
            "backup_profile": {"id": "backup", "resource_classes": ["database"]},
            "recovery": {
                "artifact_only": False,
                "data_restore": True,
                "previous_schema_constraints": {"database": ["db-1"]},
            },
            "initialization": {"supported": False},
            "release_notes": {
                "human": {"locator": "release-notes.md", "digest": digest(human)},
                "changes": {"locator": "changes.json", "digest": digest(changes)},
            },
        }
    )
    return decode(Manifest, raw), raw, human, changes


def edge(identity="one-three", source="db-1", target="db-3"):
    return {
        "id": identity,
        "from": {"database": source},
        "to": {"database": target},
        "requires": {},
        "handler_id": identity,
        "runner_profile": "migration",
        "reconcile_handler_id": identity + "-reconcile",
        "affected_resources": ["database"],
        "backup_required": True,
        "retry_policy": "after_verified_not_applied",
        "restore_profile": "restore",
    }


def profile(identity="app", host="host", application="example-app", resources=None, providers=None):
    return DeploymentProfile(
        id=identity,
        application_id=application,
        host_id=host,
        role="application",
        platform="linux/amd64",
        artifact_kind="native",
        resources=resources or {"database": "db"},
        providers=providers or {},
        operations=[
            "prepare",
            "begin",
            "close_admission",
            "drain",
            "stop",
            "snapshot",
            "restore_verify",
            "apply_step",
            "initialize",
            "activate",
            "validate",
            "reopen_admission",
            "release",
            "inspect",
            "reconcile",
            "restore",
            "verify_restored_state",
        ],
        lifecycle_profile="lifecycle",
        backup_profile="backup",
        runner_profiles=["migration"],
        restore_profiles=["restore"],
        binding_revision=digest(b"bindings"),
        maintenance_startup=True,
        isolated_restore=True,
    )


def observation(p, release_id, release="1.0.0", schema="db-1"):
    return Observation(
        deployment_id=p.id,
        application_id=p.application_id,
        manifest_digest=release_id,
        release=release,
        schemas={"database": schema},
        resource_bindings=p.resources,
        physical_binding_digests={
            r: digest(("physical-" + r).encode()) for r in p.resources.values()
        },
        profile_digest=digest(dumps(p)),
        config_revision=digest(b"config"),
        journal_revision=1,
        active_work=False,
        unknown_work=False,
        evidence=["inspection"],
        absent_resources=[],
        maintenance_epoch=0,
    )


class FakeBackend:
    """Only for isolated tests: never shipped as a working application adapter."""

    def __init__(self, obs, target_id):
        self.obs, self.target_id = obs, target_id
        self.calls, self.fail, self.crash, self.drop_proof = [], None, None, None
        self.schema, self.epochs = dict(obs.schemas), {}

    def inspect(self, p):
        return self.obs.model_copy(update={"schemas": dict(self.schema)})

    def prepare(self, p, m):
        self.calls.append("prepare")

    def perform(self, p, m, r):
        self.calls.append(r.operation)
        if r.operation == self.crash:
            raise SystemExit("simulated process death")
        if r.operation == self.fail:
            raise OSError("private provider output must never escape")
        if r.operation == "close_admission":
            self.epochs = {x: self.epochs.get(x, 0) + 1 for x in r.resource_ids}
        if r.operation in {"apply_step", "initialize"}:
            self.schema = dict(r.expected_schemas)
        if r.operation == "activate":
            self.obs = self.obs.model_copy(
                update={"manifest_digest": self.target_id, "release": m.release}
            )
        proofs = {x: True for x in PROOFS.get(r.operation, set())}
        if self.drop_proof:
            proofs.pop(self.drop_proof, None)
        return OwnerResult(
            contract_version=1,
            operation=r.operation,
            application_id=p.application_id,
            deployment_id=p.id,
            artifact_digest=m.artifact.digest,
            operation_id=r.operation_id,
            outcome="applied_verified"
            if r.operation in {"apply_step", "initialize"}
            else "verified",
            schemas=dict(self.schema),
            evidence=["evidence-" + r.operation],
            maintenance_epochs=self.epochs,
            proofs=proofs,
            snapshot_digest=digest(b"snapshot")
            if r.operation in {"snapshot", "restore_verify", "restore"}
            else None,
        )


@dataclass
class Environment:
    coordinator: Coordinator
    host: HostExecutor
    backend: FakeBackend
    releases: ReleaseStore
    profile: DeploymentProfile
    current_id: str
    target_id: str
    signer: Signer
    clock: object

    def plan(self, key="plan-key", action="update", parent=None):
        return self.coordinator.create_plan(
            "operator", action, {"app": self.target_id}, key, parent
        )

    def start(self, planned=None, key="start-key"):
        planned = planned or self.plan()
        grant = self.coordinator.authorize(
            "operator", "operator", planned["plan_id"], planned["plan_digest"]
        )["authorization_id"]
        return self.coordinator.execute(
            "operator", planned["plan_id"], planned["plan_digest"], grant, key
        )


@pytest.fixture
def environment(tmp_path):
    now = [int(time.time())]

    def clock():
        return now[0]

    private = Ed25519PrivateKey.generate().private_bytes_raw()
    release_signer, catalog_signer = Signer("release", private), Signer("catalog", private)
    keys = {
        "release": Key(release_signer.public, "example-app", "release"),
        "catalog": Key(catalog_signer.public, "example-app", "catalog"),
    }
    j = Journal(tmp_path / "coordinator")
    releases = ReleaseStore(j, keys, clock)
    old, old_raw, old_human, old_changes = manifest()
    target, raw, human, changes = manifest("1.2.0", "db-3", [edge()])
    current_id = releases.import_release(
        "example-app", old_raw, dumps(release_signer.envelope(old_raw)), old_human, old_changes
    )
    target_id = releases.import_release(
        "example-app", raw, dumps(release_signer.envelope(raw)), human, changes
    )
    cat = dumps(
        {
            "catalog_version": 1,
            "application_id": "example-app",
            "channel": "stable",
            "sequence": 1,
            "expires_at": "2099-01-01T00:00:00Z",
            "releases": [
                {
                    "release": m.release,
                    "manifest_locator": "https://releases.example.invalid/"
                    + m.release
                    + "/release.json",
                    "manifest_digest": rid,
                    "published_at": "2026-10-08T00:00:00Z",
                    "withdrawn": False,
                    "reason": "",
                }
                for m, rid in [(old, current_id), (target, target_id)]
            ],
        }
    )
    releases.accept_catalog("example-app", "stable", cat, dumps(catalog_signer.envelope(cat)))
    p = profile()
    backend = FakeBackend(observation(p, current_id), target_id)
    host_signer, coord_signer = Signer("host", private), Signer("coordinator", private)
    authority_keys = {"coordinator": Key(coord_signer.public, "example-domain", "authority")}
    receipt_keys = {"host": Key(host_signer.public, "example-domain", "receipt")}
    host = HostExecutor(
        "host",
        "example-domain",
        Journal(tmp_path / "host"),
        {p.id: p},
        releases,
        backend,
        host_signer,
        authority_keys,
        receipt_keys,
        clock,
    )
    authority = Authority(j, clock)
    authority.provision(
        "operator",
        ["read", "plan", "execute", "cancel", "recover_verify", "operator", "recover"],
        ["app"],
    )
    resources = {
        "db": Resource(
            id="db",
            owner_deployment="app",
            writers=["app"],
            backup_domain="backup",
            physical_binding_digest=digest(b"physical-db"),
            external_writers_fenced=True,
        )
    }
    coordinator = Coordinator(
        "example-domain",
        j,
        {p.id: p},
        resources,
        releases,
        {"host": host},
        authority,
        coord_signer,
        receipt_keys,
        clock,
    )
    return Environment(
        coordinator, host, backend, releases, p, current_id, target_id, coord_signer, clock
    )
