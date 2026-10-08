"""Regression counterexamples found during implementation review."""

import sqlite3
from types import SimpleNamespace

import pytest
from conftest import edge, manifest, observation, profile
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from test_execution import ticket
from test_recovery import controller

from flamoris_update_core.contracts import PROOFS, OwnerRequest
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, digest, dumps, loads
from flamoris_update_migration.runner import MigrationRunner
from flamoris_updater_adapters.journal import Journal, inspect_journal
from flamoris_updater_adapters.signing import Key, Signer


@pytest.mark.parametrize("removed", ["snapshot", "restore_verify", "validate", "stop"])
def test_signed_plan_cannot_omit_safety_phase(environment, removed):
    e = environment
    plan, _ = e.coordinator.plan(e.plan()["plan_id"])
    deleted = {s.id: s for s in plan.steps if s.operation == removed}

    def retained(ids):
        return [
            y for x in ids for y in (retained(deleted[x].predecessors) if x in deleted else [x])
        ]

    forged = plan.model_copy(
        update={
            "steps": [
                s.model_copy(update={"predecessors": retained(s.predecessors)})
                for s in plan.steps
                if s.id not in deleted
            ]
        }
    )
    with pytest.raises(UpdateError):
        e.host.run(ticket(e, "job-forged", forged, dumps(forged), forged.steps[0]))
    assert e.backend.calls == []
    assert not inspect_journal(e.host.journal.directory)["blocked_resources"]


def test_signed_plan_cannot_skip_global_barrier(environment):
    e = environment
    plan, _ = e.coordinator.plan(e.plan()["plan_id"])
    forged = plan.model_copy(
        update={
            "steps": [
                s.model_copy(update={"predecessors": []}) if s.operation == "activate" else s
                for s in plan.steps
            ]
        }
    )
    with pytest.raises(UpdateError):
        e.host.run(ticket(e, "job-forged", forged, dumps(forged), forged.steps[0]))
    assert e.backend.calls == []


@pytest.mark.parametrize("value", [True, 1.0])
def test_protocol_version_is_integer_not_boolean_or_float(value):
    _, raw, _, _ = manifest()
    obj = loads(raw)
    obj["manifest_version"] = value
    with pytest.raises(UpdateError):
        decode(Manifest, dumps(obj))


def test_disabled_initializer_cannot_supply_null_handler():
    _, raw, _, _ = manifest()
    obj = loads(raw)
    obj["initialization"]["handler_id"] = None
    with pytest.raises(UpdateError):
        decode(Manifest, dumps(obj))


def test_one_signed_manifest_selects_two_platforms():
    _, raw, _, _ = manifest()
    obj = loads(raw)
    obj["artifact_variants"] = [
        {**obj["artifact"], "platform": "linux/arm64", "digest": digest(b"arm")}
    ]
    m = decode(Manifest, dumps(obj))
    assert m.select("linux/arm64", "native").artifact.digest == digest(b"arm")
    assert m.artifact.platform == "linux/amd64"
    assert m.select("linux/amd64", "native").artifact == m.artifact
    obj["artifact_variants"].append(obj["artifact"])
    with pytest.raises(UpdateError):
        decode(Manifest, dumps(obj))


def catalog(e):
    stored = e.releases.journal.get("catalog", "example-app.stable")
    return loads(e.releases.journal.blob(stored["raw"]))


def accept(e, obj, signer=None):
    signer = signer or Signer("catalog", e.signer.private.private_bytes_raw())
    raw = dumps(obj)
    e.releases.accept_catalog("example-app", "stable", raw, dumps(signer.envelope(raw)))


def test_catalog_sequence_equivocation_and_immutable_mapping(environment):
    e = environment
    obj = catalog(e)
    obj["sequence"] = 2
    accept(e, obj)
    obj["sequence"] = 1
    with pytest.raises(UpdateError) as err:
        accept(e, obj)
    assert err.value.code == "catalog_replay"
    obj["sequence"] = 2
    obj["expires_at"] = "2098-01-01T00:00:00Z"
    with pytest.raises(UpdateError) as err:
        accept(e, obj)
    assert err.value.code == "catalog_replay"
    obj["sequence"] = 3
    obj["releases"][0]["manifest_digest"] = digest(b"different-root")
    with pytest.raises(UpdateError) as err:
        accept(e, obj)
    assert err.value.code == "immutable_release_conflict"


def test_catalog_signature_can_rotate_without_remapping_bytes(environment):
    e = environment
    rotating = Signer("new-catalog", Ed25519PrivateKey.generate().private_bytes_raw())
    e.releases.keys[rotating.identity] = Key(rotating.public, "example-app", "catalog")
    accept(e, catalog(e), rotating)
    del e.releases.keys["catalog"]
    assert e.releases.get(e.target_id).release == "1.2.0"


def test_withdrawal_and_release_key_revocation_block_new_effects(environment):
    e = environment
    obj = catalog(e)
    obj["sequence"] = 2
    obj["releases"][1]["withdrawn"] = True
    accept(e, obj)
    with pytest.raises(UpdateError):
        e.releases.get(e.target_id)
    assert e.releases.get(e.target_id, eligible=False).release == "1.2.0"
    del e.releases.keys["release"]
    with pytest.raises(UpdateError):
        e.releases.get(e.current_id, eligible=False)


def test_read_only_inspector_detects_export_lag_corruption_without_credentials(environment):
    j = environment.coordinator.journal
    j.flush_export()
    before = inspect_journal(j.directory)
    assert before["export"]["valid"] and not before["export"]["lagging"]
    with j.transaction() as db:
        j.event(db, "test", "safe")
    assert inspect_journal(j.directory)["export"]["lagging"]
    j.flush_export()
    (j.directory / "recovery.jsonl").write_bytes(b"broken\n")
    result = inspect_journal(j.directory)
    assert not result["export"]["valid"]
    assert "password" not in str(result) and "private" not in str(result)
    with j.transaction() as db:
        db.execute("UPDATE events SET digest=? WHERE sequence=1", (digest(b"tampered"),))
    with pytest.raises(UpdateError) as err:
        inspect_journal(j.directory)
    assert err.value.code == "journal_corrupt"


def test_self_preview_epoch_and_principal_revision_must_be_fresh(environment, tmp_path):
    rc, driver, ids, _ = controller(environment, tmp_path)
    preview = rc.self_update("operator", ids[1], "stale-epoch")
    rc.advance_epoch("intervening", False)
    with pytest.raises(UpdateError) as err:
        rc.self_update("operator", ids[1], "stale-epoch", preview["plan_digest"])
    assert err.value.code == "stale_plan" and driver.calls == ["prepare"]
    preview = rc.self_update("operator", ids[1], "revision")
    principal = rc.j.get("principal", "operator")
    with rc.j.transaction() as db:
        rc.j.put("principal", "operator", principal, db)
    with pytest.raises(UpdateError) as err:
        rc.self_update("operator", ids[1], "revision", preview["plan_digest"])
    assert err.value.code == "policy_changed"


def test_self_stage_failure_has_durable_unknown_tombstone(environment, tmp_path):
    rc, driver, ids, _ = controller(environment, tmp_path)
    preview = rc.self_update("operator", ids[1], "stage-failure")

    def fail(m):
        driver.calls.append("failed-stage")
        raise OSError("private effect")

    driver.prepare = fail
    result = rc.self_update("operator", ids[1], "stage-failure", preview["plan_digest"])
    assert result["state"] == "unknown" and rc.j.meta("mode") == "recovery"
    calls = list(driver.calls)
    assert (
        rc.self_update("operator", ids[1], "stage-failure", preview["plan_digest"])["state"]
        == "unknown"
    )
    assert driver.calls == calls


def test_self_inventory_survives_bootstrap_configuration(environment, tmp_path):
    rc, _, ids, _ = controller(environment, tmp_path)
    preview = rc.self_update("operator", ids[1], "accepted")
    assert (
        rc.self_update("operator", ids[1], "accepted", preview["plan_digest"])["state"]
        == "succeeded"
    )
    assert rc.current_manifest == ids[1] and rc.bootstrap_manifest == ids[0]
    next_plan = rc.self_update("operator", ids[0], "next")
    assert next_plan["previous"] == ids[1]


def test_recovery_finalizing_crash_retries_only_publication(environment, tmp_path):
    e = environment
    job = e.start()
    e.backend.fail = "reopen_admission"
    e.coordinator.run_job(job["job_id"])
    e.backend.fail = None
    rc, _, _, _ = controller(e, tmp_path)
    preview = rc.recover("operator", job["job_id"], {"app": e.current_id}, "finish-crash")
    finalize = rc._finalize_recovery
    rc._finalize_recovery = lambda *args: (_ for _ in ()).throw(
        SystemExit("crash before acceptance")
    )
    with pytest.raises(SystemExit):
        rc.recover(
            "operator",
            job["job_id"],
            {"app": e.current_id},
            "finish-crash",
            approved_digest=preview["plan_digest"],
        )
    calls = list(e.backend.calls)
    epoch = rc.j.meta("epoch")
    rc._finalize_recovery = finalize
    result = rc.recover(
        "operator",
        job["job_id"],
        {"app": e.current_id},
        "finish-crash",
        approved_digest=preview["plan_digest"],
    )
    assert result["state"] == "succeeded"
    assert e.backend.calls == calls and rc.j.meta("epoch") == epoch


def migration(tmp_path, crash=False, backup=True):
    m, _, _, _ = manifest("1.2.0", "db-3", [edge()])
    p = profile()
    db_path = tmp_path / "application.sqlite"
    with sqlite3.connect(db_path) as db:
        db.execute("PRAGMA user_version=1")
        db.execute("CREATE TABLE data(value TEXT)")
        db.execute("INSERT INTO data VALUES('irreplaceable')")
    calls = []

    def inspect():
        with sqlite3.connect(db_path) as db:
            schema = "db-" + str(db.execute("PRAGMA user_version").fetchone()[0])
        return observation(p, digest(b"manifest"), schema=schema)

    app = SimpleNamespace(
        inspect=inspect,
        fenced=lambda r: True,
        snapshot_verified=lambda r: backup,
        validate=lambda r: {k: True for k in PROOFS[r.operation]},
    )

    def handler(r):
        calls.append(r.operation_id)
        with sqlite3.connect(db_path) as db:
            db.execute("ALTER TABLE data ADD COLUMN migrated INTEGER DEFAULT 1")
            db.execute("PRAGMA user_version=3")
        if crash:
            raise SystemExit("crash after real transaction")

    runner = MigrationRunner(Journal(tmp_path / "migration"), m, p, app, {"one-three": handler})
    r = OwnerRequest(
        operation="apply_step",
        application_id=p.application_id,
        deployment_id=p.id,
        artifact_digest=m.artifact.digest,
        operation_id="step",
        job_id="job",
        plan_digest=digest(b"plan"),
        resource_ids=["db"],
        expected_schemas={"database": "db-3"},
        maintenance_epochs={"db": 1},
        predecessor_receipts=[],
        arguments=m.migrations[0].model_dump(by_alias=True),
    )
    return runner, r, calls, db_path


def test_standalone_runner_actual_database_direct_edge_and_idempotence(tmp_path):
    runner, r, calls, db_path = migration(tmp_path)
    assert runner.invoke(r).outcome == "applied_verified"
    assert runner.invoke(r).outcome == "applied_verified" and calls == ["step"]
    with sqlite3.connect(db_path) as db:
        assert db.execute("SELECT value,migrated FROM data").fetchall() == [("irreplaceable", 1)]


def test_standalone_runner_crash_does_not_replay_committed_database_change(tmp_path):
    runner, r, calls, _ = migration(tmp_path, crash=True)
    for _ in range(2):
        with pytest.raises(UpdateError) as err:
            runner.invoke(r)
        assert err.value.code == "outcome_unknown"
    assert calls == ["step"]


def test_standalone_runner_requires_verified_backup_before_intent(tmp_path):
    runner, r, calls, _ = migration(tmp_path, backup=False)
    with pytest.raises(UpdateError) as err:
        runner.invoke(r)
    assert err.value.code == "backup_unverified" and calls == []
    assert runner.journal.get("migration_operation", r.operation_id) is None


def test_notes_escaped_large_chunks_are_bounded_complete_and_range_bound(environment):
    e = environment
    _, raw, _, changes = manifest("1.3.0")
    human = ('"\\\n\x01猫' * 20000).encode()
    obj = loads(raw)
    obj["release_notes"]["human"]["digest"] = digest(human)
    raw = dumps(obj)
    release_signer = Signer("release", e.signer.private.private_bytes_raw())
    rid = e.releases.import_release(
        "example-app", raw, dumps(release_signer.envelope(raw)), human, changes
    )
    obj = catalog(e)
    obj["sequence"] = 2
    obj["releases"].append(
        {
            "release": "1.3.0",
            "manifest_digest": rid,
            "manifest_locator": "release.json",
            "published_at": "2026-10-08T00:00:00Z",
            "withdrawn": False,
            "reason": "",
        }
    )
    accept(e, obj)
    cursor, assembled, seen = "", "", set()
    while True:
        result = e.releases.notes("example-app", "1.2.0", "1.3.0", cursor)
        assert len(dumps(result)) < 2 * 1024 * 1024
        assembled += "".join(x["human"] for x in result["entries"])
        cursor = result["next_cursor"]
        if not cursor:
            assert result["complete"]
            break
        assert cursor not in seen
        seen.add(cursor)
        with pytest.raises(UpdateError):
            e.releases.notes("example-app", "1.0.0", "1.3.0", cursor)
    assert assembled.encode() == human


def test_shared_resource_migrates_only_at_owner_and_orders_writers():
    from flamoris_update_core.inventory import Resource
    from flamoris_update_core.planner import Planner

    owner, consumer = profile("owner"), profile("consumer")
    resource = Resource(
        id="db",
        owner_deployment="owner",
        writers=["owner", "consumer"],
        backup_domain="backup",
        physical_binding_digest=digest(b"physical-db"),
        external_writers_fenced=True,
    )
    planner = Planner({p.id: p for p in [owner, consumer]}, {"db": resource})
    old, _, _, _ = manifest()
    target, _, _, _ = manifest("1.2.0", "db-3", [edge()])
    consumer_target, _, _, _ = manifest("1.2.0", "db-3")
    observations = {p.id: observation(p, digest(p.id.encode())) for p in [owner, consumer]}
    args = (
        "update",
        {"owner": digest(b"target"), "consumer": digest(b"consumer-target")},
        {"owner": target, "consumer": consumer_target},
        observations,
        {"owner": old, "consumer": old},
        100,
        1,
        1,
    )
    plan = planner.build(*args)
    assert [s.deployment_id for s in plan.steps if s.operation == "apply_step"] == ["owner"]
    assert all(
        s.resources == ([] if s.deployment_id == "consumer" else ["db"])
        for s in plan.steps
        if s.operation in {"snapshot", "restore_verify"}
    )
    assert [s.deployment_id for s in plan.steps if s.operation == "stop"] == ["consumer", "owner"]
    assert [s.deployment_id for s in plan.steps if s.operation == "activate"] == [
        "owner",
        "consumer",
    ]
    with pytest.raises(UpdateError) as err:
        planner.build(*args[:2], {"owner": target, "consumer": old}, *args[3:])
    assert err.value.code == "incompatible_dependency"


def test_physical_resource_identity_drift_stops_before_effect(environment):
    e = environment
    e.host.resources = e.coordinator.planner.resources
    e.backend.obs = e.backend.obs.model_copy(
        update={"physical_binding_digests": {"db": digest(b"other-database")}}
    )
    with pytest.raises(UpdateError):
        e.plan()
    assert e.backend.calls == []


@pytest.mark.parametrize("allowed", [True, False])
def test_real_unix_peer_credentials_and_frame_admission(environment, allowed):
    import os
    import socket
    import struct
    import threading

    from flamoris_updater_adapters.helper import Dispatch, serve_connection
    from flamoris_updater_adapters.transport import receive_exact

    e = environment
    server, client = socket.socketpair()
    thread = threading.Thread(
        target=serve_connection,
        args=(server, Dispatch(e.host), [os.geteuid()] if allowed else [os.geteuid() + 1]),
    )
    thread.start()
    packet = e.signer.packet(
        {
            "command": "inspect",
            "domain": "example-domain",
            "host_id": "host",
            "epoch": 1,
            "deployment_id": "app",
        }
    )
    raw = dumps(packet)
    client.sendall(struct.pack("!I", len(raw)) + raw)
    size = struct.unpack("!I", receive_exact(client, 4))[0]
    result = loads(receive_exact(client, size))
    thread.join(timeout=3)
    server.close()
    client.close()
    assert not thread.is_alive()
    assert (result.get("deployment_id") == "app") if allowed else result["error"] == "forbidden"


def test_oversized_helper_frame_is_rejected_before_payload_read():
    from flamoris_updater_adapters.transport import receive_exact

    with pytest.raises(UpdateError) as err:
        receive_exact(None, 1024 * 1024 + 1)
    assert err.value.code == "quota_exceeded"


def test_compatibility_rejects_unknown_control_tables(environment):
    from flamoris_updater_adapters.compatibility import inspect_control

    with environment.coordinator.journal.transaction() as db:
        db.execute("CREATE TABLE future_control(value TEXT)")
    with pytest.raises(ValueError):
        inspect_control(environment.coordinator.journal.directory)


def test_offline_token_revocation_and_user_disable_take_effect(environment):
    from flamoris_updater_adapters.auth import AuthStore

    e = environment
    auth = AuthStore(e.coordinator.journal, e.coordinator.authority, e.clock)
    one, two = auth.issue_token("operator"), auth.issue_token("operator")
    auth.revoke_token("operator", one)
    with pytest.raises(UpdateError):
        auth.bearer(one)
    assert auth.bearer(two) == "operator"
    auth.disable_user("operator")
    with pytest.raises(UpdateError):
        auth.bearer(two)


def test_docker_command_is_bound_to_configured_daemon_and_rejects_implicit_volumes():
    from flamoris_updater_adapters.docker import DockerDriver

    driver = DockerDriver.__new__(DockerDriver)
    driver.binding = SimpleNamespace(
        daemon_socket="/protected/docker.sock",
        docker_config_directory="/protected/docker-config",
        registry_origin="https://registry.example.invalid",
        repository="application",
    )
    calls = []
    image = {
        "Id": digest(b"config"),
        "Os": "linux",
        "Architecture": "amd64",
        "RepoDigests": ["registry.example.invalid/application@" + digest(b"child")],
        "RootFS": {"Layers": [digest(b"expanded")]},
        "Config": {"Volumes": None},
    }

    def command(argv, **kwargs):
        calls.append(argv)
        return b"[" + dumps(image) + b"]"

    driver.command = command
    prepared = {
        "selected_digest": digest(b"child"),
        "config_digest": digest(b"config"),
        "platform": "linux/amd64",
        "diff_ids": [digest(b"expanded")],
    }
    assert driver._image(prepared).endswith(prepared["selected_digest"])
    assert calls[0][:5] == [
        "/usr/bin/docker",
        "--host",
        "unix:///protected/docker.sock",
        "--config",
        "/protected/docker-config",
    ]
    image["Config"]["Volumes"] = {"/anonymous": {}}
    with pytest.raises(UpdateError):
        driver._image(prepared)


def test_self_intent_atomically_gates_normal_admission_before_stop(environment, tmp_path):
    rc, driver, ids, _ = controller(environment, tmp_path)
    preview = rc.self_update("operator", ids[1], "atomic-gate")
    export = rc.j.flush_export
    rc.j.flush_export = lambda: (_ for _ in ()).throw(SystemExit("crash after durable intent"))
    with pytest.raises(SystemExit):
        rc.self_update("operator", ids[1], "atomic-gate", preview["plan_digest"])
    assert rc.j.meta("mode") == "recovery" and driver.calls == ["prepare"]
    rc.j.flush_export = export
    result = rc.self_update("operator", ids[1], "atomic-gate", preview["plan_digest"])
    assert result["state"] == "unknown" and driver.calls == ["prepare"]


def test_restore_verification_cannot_substitute_another_owners_snapshot(environment):
    e = environment
    original = e.backend.perform

    def perform(p, m, r):
        result = original(p, m, r)
        if r.operation == "restore_verify":
            foreign = result.model_copy(
                update={
                    "operation": "snapshot",
                    "deployment_id": "other-owner",
                    "operation_id": "foreign-snapshot",
                    "snapshot_digest": digest(b"foreign-snapshot"),
                }
            )
            packet = e.host.signer.packet({"result": foreign.model_dump()})
            with e.host.journal.transaction() as db:
                db.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,?)",
                    (
                        "foreign-snapshot",
                        r.job_id,
                        digest(b"foreign-binding"),
                        dumps({}),
                        "verified",
                        dumps(packet),
                    ),
                )
            return result.model_copy(update={"snapshot_digest": foreign.snapshot_digest})
        return result

    e.backend.perform = perform
    job = e.start()
    e.coordinator.run_job(job["job_id"])
    assert e.coordinator.job("operator", job["job_id"])["state"] == "unknown"
    assert "apply_step" not in e.backend.calls


def test_application_environment_bytes_are_part_of_configuration_guard(tmp_path):
    from flamoris_updater_adapters.runtime import configuration_guard, credential_files

    configuration = tmp_path / "host.json"
    configuration.write_bytes(b"protected-host")
    environment = tmp_path / "application.env"
    environment.write_bytes(b"SETTING=first")
    environment.chmod(0o600)
    cfg = SimpleNamespace(model_dump=lambda: {"binding": {"environment_file": str(environment)}})
    guard = configuration_guard(configuration, files=credential_files(cfg))
    guard()
    environment.write_bytes(b"SETTING=second")
    with pytest.raises(UpdateError) as error:
        guard()
    assert error.value.code == "policy_changed"


@pytest.mark.parametrize(
    "field,replacement",
    [
        ("Memory", 0),
        ("PidsLimit", 0),
        ("CapDrop", []),
        ("NetworkMode", "host"),
        ("Tmpfs", {}),
        ("PortBindings", {"80/tcp": [{"HostIp": "0.0.0.0", "HostPort": "80"}]}),
        ("Devices", [{"PathOnHost": "/unapproved"}]),
    ],
)
def test_activation_attestation_refuses_changed_container_policy(field, replacement):
    from flamoris_updater_adapters.docker import DockerDriver

    driver = DockerDriver.__new__(DockerDriver)
    driver.binding = SimpleNamespace(
        container_name="synthetic",
        runtime_user="1000:1000",
        mounts=[],
        ports=[],
        network="isolated",
        memory_bytes=1024,
        pids_limit=32,
    )
    driver._validate_binding = lambda: None
    driver.preparation_id = lambda _: "prepared"
    driver.journal = SimpleNamespace(get=lambda *_: {"config_digest": digest(b"config")})
    driver._image = lambda _: "trusted-locator"
    inspection = {
        "Image": digest(b"config"),
        "State": {"Running": True},
        "Mounts": [],
        "Config": {
            "Image": "trusted-locator",
            "User": "1000:1000",
            "Labels": {"flamoris.updater.operation": "operation"},
        },
        "HostConfig": {
            "ReadonlyRootfs": True,
            "Privileged": False,
            "NetworkMode": "isolated",
            "Memory": 1024,
            "PidsLimit": 32,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": "rw,noexec,nosuid,nodev,size=268435456,mode=1777"},
        },
    }
    driver._docker = lambda *_: dumps([inspection])
    driver.verify_active(None, "operation")
    inspection["HostConfig"][field] = replacement
    with pytest.raises(UpdateError):
        driver.verify_active(None, "operation")
