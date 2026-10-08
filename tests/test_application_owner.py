import base64

import pytest
from conftest import manifest, profile

from flamoris_update_core.contracts import OwnerRequest, verified
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.owner import ApplicationOwner, DomainState, OwnerConfiguration, TrustKey
from flamoris_update_core.resources import TreeBinding
from flamoris_update_core.signing import Signer
from flamoris_update_core.wire import digest, dumps


def configured(tmp_path):
    target, raw, _, _ = manifest()
    p = profile()
    release = Signer("release-key", b"a" * 32)
    host = Signer(p.host_id, b"b" * 32)
    path = tmp_path / "manifest.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    path.with_name(path.name + ".sig").write_bytes(dumps(release.envelope(raw)))
    path.with_name(path.name + ".sig").chmod(0o600)
    root = tmp_path / "data"
    root.mkdir(mode=0o700)
    (root / "history").write_bytes(b"irreplaceable")
    cfg = OwnerConfiguration(
        profile=p,
        state_directory=str(tmp_path / "state"),
        snapshot_directory=str(tmp_path / "backups"),
        trees=[TreeBinding(id="database", path=str(root), max_files=10, max_bytes=4096)],
        postgres=[],
        release_files=[str(path)],
        domain_configuration={},
        trust_keys=[
            TrustKey(
                id=s.identity,
                domain=domain,
                purpose=purpose,
                public_base64=base64.b64encode(s.public).decode(),
            )
            for s, domain, purpose in [
                (release, p.application_id, "release"),
                (host, p.host_id, "receipt"),
            ]
        ],
    )
    owner = ApplicationOwner(
        cfg,
        p.application_id,
        "1.0.0",
        lambda *_: DomainState(schemas={"database": "db-1"}, active_work=False, unknown_work=False),
    )
    return owner, target, host, digest(raw)


def request(owner, target, operation, *, job="entry-job", **arguments):
    epoch = owner.gate.state()["epoch"]
    return OwnerRequest(
        operation=operation,
        application_id=owner.profile.application_id,
        deployment_id=owner.profile.id,
        artifact_digest=target.artifact.digest,
        operation_id=job + "." + operation,
        job_id=job,
        plan_digest=digest(b"plan"),
        resource_ids=list(owner.profile.resources.values()),
        expected_schemas=target.schema_targets,
        maintenance_epochs={} if epoch == 0 else {"db": epoch},
        predecessor_receipts=[],
        arguments=arguments,
    )


def run(owner, target, operation, **kwargs):
    req = request(owner, target, operation, **kwargs)
    result = owner.perform(req)
    verified(req, result)
    return result


def test_entry_cycle_requires_real_backup_host_attestation_and_boot(tmp_path):
    owner, target, host, root_digest = configured(tmp_path)
    for operation in [
        "prepare",
        "begin",
        "close_admission",
        "drain",
        "stop",
        "snapshot",
        "restore_verify",
    ]:
        run(owner, target, operation, standalone_transition=True)
    req = request(owner, target, "activate")
    activation = host.packet(
        dict(
            kind="host_activation",
            application_id=req.application_id,
            deployment_id=req.deployment_id,
            artifact_digest=req.artifact_digest,
            manifest_digest=root_digest,
            operation_id=req.operation_id,
            job_id=req.job_id,
            plan_digest=req.plan_digest,
        )
    )
    with owner.journal.transaction() as db:
        owner.journal.put(
            "application_boot",
            req.application_id,
            {"release": "1.0.0", "epoch": owner.gate.state()["epoch"], "job_id": req.job_id},
            db,
        )
    run(owner, target, "activate", host_activation=activation)
    run(owner, target, "validate")
    run(owner, target, "reopen_admission")
    run(owner, target, "release")
    assert not owner.gate.state()["closed"]
    assert owner.inspect("fresh-observation").entry_evidence == "standalone_transition"


def test_second_job_cannot_claim_prepared_application(tmp_path):
    owner, target, _, _ = configured(tmp_path)
    run(owner, target, "begin")
    with pytest.raises(UpdateError) as failure:
        run(owner, target, "begin", job="foreign-job")
    assert failure.value.code == "maintenance_conflict"


def test_failed_owner_operation_remains_unknown_across_restart(tmp_path):
    owner, target, _, _ = configured(tmp_path)
    run(owner, target, "begin")
    run(owner, target, "close_admission")
    with pytest.raises(UpdateError):
        run(owner, target, "activate", host_activation={})
    restarted = ApplicationOwner(
        owner.config, owner.profile.application_id, "1.0.0", owner.inspect_domain
    )
    assert restarted.inspect("after-restart").unknown_work
    with pytest.raises(UpdateError) as failure:
        run(restarted, target, "drain")
    assert failure.value.code == "recovery_required"


def test_reopen_without_verified_activation_is_rejected(tmp_path):
    owner, target, _, _ = configured(tmp_path)
    for operation in ["begin", "close_admission", "drain", "snapshot", "restore_verify"]:
        run(owner, target, operation)
    with pytest.raises(UpdateError):
        run(owner, target, "reopen_admission")
    assert owner.gate.state()["closed"]


def test_configuration_revision_cannot_change_during_claim(tmp_path):
    owner, target, _, _ = configured(tmp_path)
    revision = {"value": digest(b"original")}
    owner.inspect_domain = lambda *_: DomainState(
        schemas={"database": "db-1"},
        active_work=False,
        unknown_work=False,
        configuration_digest=revision["value"],
    )
    run(owner, target, "begin")
    revision["value"] = digest(b"changed")
    with pytest.raises(UpdateError):
        run(owner, target, "close_admission")
    assert owner.gate.state()["epoch"] == 0
    assert owner.journal.get("application_claim", owner.profile.id)["job_id"] == "entry-job"
