import json
from types import SimpleNamespace

import pytest
from conftest import manifest, profile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from flamoris_update_core.contracts import OwnerResult
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps, loads
from flamoris_updater_adapters.compatibility import inspect_control
from flamoris_updater_adapters.control import HostControl
from flamoris_updater_adapters.recovery import RecoveryController
from flamoris_updater_adapters.signing import Key, Signer


def controller(environment, tmp_path):
    e = environment
    p = profile("updater", application="flamoris-updater").model_copy(
        update={"role": "coordinator"}
    )
    e.coordinator.profiles[p.id] = p
    e.host.profiles[p.id] = p
    e.coordinator.authority.provision(
        "operator",
        ["read", "plan", "execute", "cancel", "recover_verify", "operator", "recover"],
        ["app", "updater"],
    )
    signing = Signer("controller", Ed25519PrivateKey.generate().private_bytes_raw())
    e.host.authorities[signing.identity] = Key(signing.public, "example-domain", "controller")
    control = HostControl(e.host)
    e.host.protected = control.invoke

    class Driver:
        def __init__(self):
            self.store = SimpleNamespace(root=tmp_path / "bundles")
            self.store.root.mkdir()
            self.control_state_directory = e.coordinator.journal.directory
            interpreter = tmp_path / "test-python3.12"
            interpreter.write_bytes(b"test-only command adapter")
            interpreter.chmod(0o555)
            self.python_executable = str(interpreter)
            self.calls = []

        def stop(self):
            self.calls.append("stop")

        def prepare(self, m):
            self.calls.append("prepare")
            path = self.store.root / m.artifact.digest.removeprefix("sha256:")
            path.mkdir(exist_ok=True)
            (path / "bundle-compatibility.json").write_text(
                json.dumps(
                    {
                        "compatibility_version": 1,
                        "journal_version": 1,
                        "control_store_version": 1,
                        "recovery_protocol_version": 1,
                        "package": "flamoris-updater",
                        "version": m.release,
                    }
                )
            )
            probe = path / "site-packages/flamoris_updater_adapters/compatibility.py"
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("# indexed test candidate")

        def activate(self, m, op):
            self.calls.append(("activate", m.release))

        def command(self, argv, **kwargs):
            assert argv[1] == "-I"
            return dumps(inspect_control(self.control_state_directory))

    driver = Driver()
    e.backend.drivers = {"updater": driver}
    old_perform = e.backend.perform

    def perform(p, m, r):
        if r.operation == "reconcile":
            return OwnerResult(
                contract_version=1,
                operation="reconcile",
                application_id=p.application_id,
                deployment_id=p.id,
                artifact_digest=m.artifact.digest,
                operation_id=r.operation_id,
                outcome="partial_known",
                schemas=e.backend.schema,
                evidence=["owner-fenced"],
                maintenance_epochs=e.backend.epochs,
                proofs={
                    "writers_fenced": True,
                    "unknown_work_absent": True,
                    "durable_maintenance": True,
                },
            )
        if r.operation == "restore":
            e.backend.schema = dict(r.expected_schemas)
        if r.operation == "activate":
            e.backend.target_id = next(
                x["id"]
                for x in e.releases.journal.list("release")
                if x["application_id"] == p.application_id and x["release"] == m.release
            )
        return old_perform(p, m, r)

    e.backend.perform = perform
    updater_signing = Signer("updater-release", Ed25519PrivateKey.generate().private_bytes_raw())
    catalog_signing = Signer("updater-catalog", Ed25519PrivateKey.generate().private_bytes_raw())
    e.releases.keys.update(
        {
            updater_signing.identity: Key(updater_signing.public, "flamoris-updater", "release"),
            catalog_signing.identity: Key(catalog_signing.public, "flamoris-updater", "catalog"),
        }
    )
    entries = []
    ids = []
    for release in ["1.0.0", "1.1.0"]:
        _, raw, human, changes = manifest(release, application="flamoris-updater")
        obj = loads(raw)
        obj["schema_targets"] = {"control": "updater-control-1"}
        obj["artifact"]["digest"] = digest(release.encode())
        raw = dumps(obj)
        rid = e.releases.import_release(
            "flamoris-updater", raw, dumps(updater_signing.envelope(raw)), human, changes
        )
        entries.append(
            {
                "release": release,
                "manifest_locator": "release.json",
                "manifest_digest": rid,
                "published_at": "2026-10-08T00:00:00Z",
                "withdrawn": False,
                "reason": "",
            }
        )
        ids.append(rid)
    cat = dumps(
        {
            "catalog_version": 1,
            "application_id": "flamoris-updater",
            "channel": "stable",
            "sequence": 1,
            "expires_at": "2099-01-01T00:00:00Z",
            "releases": entries,
        }
    )
    e.releases.accept_catalog(
        "flamoris-updater", "stable", cat, dumps(catalog_signing.envelope(cat))
    )
    driver.prepare(e.releases.get(ids[0]))
    rc = RecoveryController(e.coordinator, signing, "updater", ids[0], None)
    rc._ready = lambda version, epoch: {
        "version": version,
        "epoch": epoch,
        "mode": e.coordinator.journal.meta("mode"),
        "journal_version": 1,
    }
    return rc, driver, ids, control


def test_recovery_preview_verify_keeps_parent_blocks(environment, tmp_path):
    e = environment
    job = e.start()
    e.backend.fail = "reopen_admission"
    e.coordinator.run_job(job["job_id"])
    e.backend.fail = None
    rc, _, _, _ = controller(e, tmp_path)
    preview = rc.recover("operator", job["job_id"], {"app": e.target_id}, "verify-key", True)
    assert "plan_digest" in preview
    child = rc.recover(
        "operator", job["job_id"], {"app": e.target_id}, "verify-key", True, preview["plan_digest"]
    )
    assert child["state"] == "succeeded"
    assert e.coordinator.job("operator", job["job_id"])["blocked_resources"] == ["db"]
    assert e.host.journal.get("parent_resolution", job["job_id"]) is None


def test_linked_restore_uses_original_snapshot_and_atomic_resolution(environment, tmp_path):
    e = environment
    job = e.start()
    e.backend.fail = "reopen_admission"
    e.coordinator.run_job(job["job_id"])
    e.backend.fail = None
    rc, _, _, _ = controller(e, tmp_path)
    preview = rc.recover("operator", job["job_id"], {"app": e.current_id}, "recover-key")
    with pytest.raises(UpdateError) as rejected:
        rc.recover(
            "operator",
            job["job_id"],
            {"app": e.current_id},
            "recover-key",
            approved_digest=digest(b"wrong"),
        )
    assert rejected.value.code == "stale_plan"
    child = rc.recover(
        "operator",
        job["job_id"],
        {"app": e.current_id},
        "recover-key",
        approved_digest=preview["plan_digest"],
    )
    assert child["state"] == "succeeded", child
    parent = e.coordinator.job("operator", job["job_id"])
    assert (
        parent["state"] == "unknown"
        and parent["resolution_job_id"] == child["job_id"]
        and parent["blocked_resources"] == []
    )
    assert e.backend.schema == {"database": "db-1"}
    assert e.host.journal.get("parent_resolution", job["job_id"])["resolved"]
    assert (
        rc.recover(
            "operator",
            job["job_id"],
            {"app": e.current_id},
            "recover-key",
            approved_digest=preview["plan_digest"],
        )["job_id"]
        == child["job_id"]
    )


def test_self_update_requires_exact_approval_and_preserves_grants(environment, tmp_path):
    rc, driver, ids, _ = controller(environment, tmp_path)
    preview = rc.self_update("operator", ids[1], "self-key")
    assert "plan_digest" in preview and driver.calls == ["prepare"]
    result = rc.self_update("operator", ids[1], "self-key", preview["plan_digest"])
    assert result["state"] == "succeeded"
    assert environment.coordinator.journal.meta("epoch") == "2"
    assert environment.host.journal.meta("epoch") == "2"
    calls = list(driver.calls)
    assert (
        rc.self_update("operator", ids[1], "self-key", preview["plan_digest"])["state"]
        == "succeeded"
    )
    assert driver.calls == calls


def test_self_rollback_uses_new_epoch_without_database_restore(environment, tmp_path):
    rc, driver, ids, _ = controller(environment, tmp_path)

    def ready(version, epoch):
        if version == "1.1.0":
            raise UpdateError("outcome_unknown")
        return {"version": version, "epoch": epoch}

    rc._ready = ready
    preview = rc.self_update("operator", ids[1], "rollback")
    result = rc.self_update("operator", ids[1], "rollback", preview["plan_digest"])
    assert result["state"] == "failed_safe" and result["epoch"] == 3
    assert driver.calls[-1] == ("activate", "1.0.0")
    assert environment.coordinator.journal.get("principal", "operator")["active"]
    assert environment.coordinator.journal.get("self_plan", preview["plan_id"]) is not None


def test_missing_host_ack_blocks_handoff(environment, tmp_path):
    rc, _, _, _ = controller(environment, tmp_path)
    rc.c.hosts["unreachable"] = SimpleNamespace(
        protected=lambda packet: (_ for _ in ()).throw(UpdateError("release_unavailable"))
    )
    with pytest.raises(UpdateError):
        rc.advance_epoch("partial", False)
    assert rc.j.meta("epoch") == "1"
    assert environment.host.journal.meta("mode") == "maintenance"


def test_compatibility_is_read_only_and_covers_control_records(environment):
    j = environment.coordinator.journal
    before = inspect_control(j.directory)
    assert inspect_control(j.directory) == before
    environment.coordinator.authority.provision("operator", ["read"], ["app"])
    assert inspect_control(j.directory)["control_digest"] != before["control_digest"]
