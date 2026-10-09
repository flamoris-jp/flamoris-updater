import pytest
from pydantic import ValidationError

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import Observation
from flamoris_update_core.models import Plan
from flamoris_updater_adapters.cli import main


@pytest.mark.parametrize("tool", ["updater_enrollment_plan", "updater_enroll_execute"])
def test_cli_rejects_removed_import_tools_before_accessing_inputs(tool, capsys):
    with pytest.raises(SystemExit) as failure:
        main(
            [
                "call",
                "--url",
                "https://updater.example.invalid",
                "--token-file",
                "/absent/token",
                "--ca",
                "/absent/ca",
                "--cert",
                "/absent/cert",
                "--key",
                "/absent/key",
                "--tool",
                tool,
            ]
        )
    assert failure.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_import_action_rejected_before_inspection_or_persistence(environment):
    e = environment

    def unexpected_inspection(*_):
        pytest.fail("Removed import action must not inspect an existing deployment")

    e.host.inspect = unexpected_inspection
    with pytest.raises(UpdateError) as failure:
        e.coordinator.create_plan("operator", "enroll", {"app": e.target_id}, "import")
    assert failure.value.code == "invalid_input"
    with e.coordinator.journal.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM jobs").fetchone()[0] == 0


def test_old_import_plan_cannot_be_decoded_as_an_update(environment):
    e = environment
    result = e.coordinator.create_plan("operator", "update", {"app": e.target_id}, "update")
    plan, _ = e.coordinator.plan(result["plan_id"])
    with pytest.raises(ValidationError):
        Plan.model_validate({**plan.model_dump(), "action": "enroll"})


def test_import_authority_role_is_not_provisioned(environment):
    authority = environment.coordinator.authority
    with pytest.raises(UpdateError) as failure:
        authority.provision("importer", ["read", "enroll"], ["app"])
    assert failure.value.code == "invalid_input"
    assert authority.journal.get("principal", "importer") is None


@pytest.mark.parametrize(
    "evidence", ["standalone_transition", "verified_adoption", "verified_installation"]
)
def test_old_import_evidence_is_not_an_observation_contract(environment, evidence):
    payload = environment.backend.obs.model_dump()
    payload["entry_evidence"] = evidence
    with pytest.raises(ValidationError):
        Observation.model_validate(payload)


def test_unmanaged_deployment_cannot_enter_via_normal_update(environment):
    e = environment
    e.backend.obs = e.backend.obs.model_copy(update={"manifest_digest": None, "release": None})
    with pytest.raises(UpdateError) as failure:
        e.coordinator.create_plan("operator", "update", {"app": e.target_id}, "unmanaged")
    assert failure.value.code == "unsupported_entry"
    assert not e.backend.calls
    assert e.coordinator.journal.get("inventory", "app") is None
