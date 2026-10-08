from types import SimpleNamespace

import pytest
from test_application_owner import configured

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps
from flamoris_updater_adapters.backends import ApplicationBackend
from flamoris_updater_adapters.entry_cli import EntryConfiguration, EntryTransition
from flamoris_updater_adapters.journal import Journal


def transition(tmp_path):
    owner, target, signing, root_digest = configured(tmp_path)
    state = {"image_id": digest(b"old"), "container_id": "fixed-old"}

    class OwnerPort:
        def inspect(self, _):
            return owner.inspect("fresh")

        def perform(self, request):
            return owner.perform(request)

    class Driver:
        fail = False

        def source_state(self):
            return state

        def prepare(self, _):
            pass

        def stop(self):
            pass

        def activate(self, _, operation_id):
            if self.fail:
                raise OSError("private failure")
            with owner.journal.transaction() as db:
                owner.journal.put(
                    "application_boot",
                    owner.profile.application_id,
                    {
                        "release": target.release,
                        "epoch": owner.gate.state()["epoch"],
                        "job_id": operation_id.rsplit(".", 1)[0],
                    },
                    db,
                )

        def verify_active(self, *_):
            pass

    driver = Driver()
    backend = ApplicationBackend(
        {owner.profile.id: OwnerPort()}, {owner.profile.id: driver}, signing
    )
    host = SimpleNamespace(
        journal=Journal(tmp_path / "host"),
        backend=backend,
        inspect=lambda _: owner.inspect("fresh"),
        clock=lambda: 2000000000,
        guard=lambda: None,
    )
    cfg = EntryConfiguration(
        helper_config_file="/protected/helper.json",
        deployment_id=owner.profile.id,
        manifest_file="/protected/manifest.json",
        baseline_tag="v0.1",
        baseline_revision="a" * 40,
        expected_source_state_digest=digest(dumps(state)),
    )
    return (
        EntryTransition(cfg, host, owner.profile, target, root_digest, digest(b"config")),
        owner,
        driver,
        state,
    )


def test_entry_complete_cycle_and_replay_refused(tmp_path):
    entry, owner, _, _ = transition(tmp_path)
    plan = entry.plan()
    result = entry.apply(plan, digest(dumps(plan)))
    assert result["phase"] == "succeeded" and result["enrollment_required"]
    assert not owner.gate.state()["closed"]
    with pytest.raises(UpdateError):
        entry.apply(plan, digest(dumps(plan)))


def test_source_replacement_after_plan_has_no_effect(tmp_path):
    entry, owner, _, source = transition(tmp_path)
    plan = entry.plan()
    source["image_id"] = digest(b"changed")
    with pytest.raises(UpdateError):
        entry.apply(plan, digest(dumps(plan)))
    assert owner.gate.state()["epoch"] == 0
    assert entry.host.journal.get("entry_job", plan.id) is None


def test_activation_failure_preserves_closed_gate_and_claims(tmp_path):
    entry, owner, driver, _ = transition(tmp_path)
    plan = entry.plan()
    driver.fail = True
    with pytest.raises(OSError):
        entry.apply(plan, digest(dumps(plan)))
    assert owner.gate.state()["closed"]
    assert entry.host.journal.get("entry_job", plan.id)["phase"] == "recovery_required"
    with entry.host.journal.connection() as db:
        assert db.execute("SELECT 1 FROM claims WHERE job_id=?", (plan.id,)).fetchone()
    with pytest.raises(UpdateError):
        entry.apply(plan, digest(dumps(plan)))


def test_configuration_change_between_steps_keeps_claim_and_stops_effects(tmp_path):
    entry, owner, driver, _ = transition(tmp_path)
    plan = entry.plan()

    def changed():
        raise UpdateError("policy_changed")

    driver.prepare = lambda _: setattr(entry.host, "guard", changed)
    with pytest.raises(UpdateError) as error:
        entry.apply(plan, digest(dumps(plan)))
    assert error.value.code == "policy_changed"
    assert owner.journal.get("application_claim", owner.profile.id) is None
    assert entry.host.journal.get("entry_job", plan.id)["phase"] == "recovery_required"
    with entry.host.journal.connection() as db:
        assert db.execute("SELECT 1 FROM claims WHERE job_id=?", (plan.id,)).fetchone()
