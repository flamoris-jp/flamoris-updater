import base64

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.journal import inspect_journal


def ticket(env, job, plan, raw, step, predecessors=None):
    return env.signer.packet(
        {
            "ticket_version": 1,
            "domain": "example-domain",
            "host_id": "host",
            "epoch": 1,
            "admitted_at": env.clock(),
            "job_id": job,
            "plan": base64.b64encode(raw).decode(),
            "step_id": step.id,
            "predecessors": predecessors or {},
        }
    )


def test_update_finishes_after_reopening_and_final_receipts(environment):
    e = environment
    job = e.start()
    assert job["state"] == "accepted"
    e.coordinator.run_job(job["job_id"])
    outcome = e.coordinator.job("operator", job["job_id"])
    assert outcome["state"] == "succeeded", outcome
    assert (
        e.backend.calls.index("restore_verify")
        < e.backend.calls.index("apply_step")
        < e.backend.calls.index("activate")
        < e.backend.calls.index("validate")
        < e.backend.calls.index("reopen_admission")
        < e.backend.calls.index("release")
    )
    assert not inspect_journal(e.coordinator.journal.directory)["blocked_resources"]
    assert e.backend.schema == {"database": "db-3"}


def test_one_plan_across_keys_and_grants_and_payload_conflict(environment):
    e = environment
    planned = e.plan()
    first = e.start(planned)
    second = e.start(planned, "different-key")
    assert first["job_id"] == second["job_id"]
    assert e.plan()["plan_id"] == planned["plan_id"]
    with pytest.raises(UpdateError) as err:
        e.coordinator.create_plan("operator", "update", {"app": e.current_id}, "plan-key")
    assert err.value.code == "idempotency_conflict"


def test_operation_conflict_and_global_predecessor_enforcement(environment):
    e = environment
    p = e.plan()
    plan, raw = e.coordinator.plan(p["plan_id"])
    first = plan.steps[0]
    assert e.host.run(ticket(e, "job-test", plan, raw, first))["outcome"] == "verified"
    altered = plan.model_copy(update={"created_at": plan.created_at - 1})
    with pytest.raises(UpdateError) as err:
        e.host.run(ticket(e, "job-test", altered, dumps(altered), first))
    assert err.value.code == "operation_conflict"
    activate = next(s for s in plan.steps if s.operation == "activate")
    with pytest.raises(UpdateError):
        e.host.run(ticket(e, "job-test", plan, raw, activate))
    assert "activate" not in e.backend.calls


@pytest.mark.parametrize(
    "operation",
    [
        "snapshot",
        "restore_verify",
        "apply_step",
        "activate",
        "validate",
        "reopen_admission",
        "release",
    ],
)
def test_lost_effect_response_keeps_blockers_no_retry(environment, operation):
    e = environment
    e.backend.fail = operation
    job = e.start()
    e.coordinator.run_job(job["job_id"])
    outcome = e.coordinator.job("operator", job["job_id"])
    assert outcome["state"] == "unknown"
    assert inspect_journal(e.coordinator.journal.directory)["blocked_resources"]
    assert "private provider" not in str(outcome)
    count = len(e.backend.calls)
    e.coordinator.run_job(job["job_id"])
    assert len(e.backend.calls) == count


def test_process_death_after_intent_is_not_replayed(environment):
    e = environment
    e.backend.crash = "apply_step"
    job = e.start()
    with pytest.raises(SystemExit):
        e.coordinator.run_job(job["job_id"])
    e.host.journal.recover_intents()
    assert inspect_journal(e.host.journal.directory)["unsettled_operations"]
    assert inspect_journal(e.host.journal.directory)["blocked_resources"]
    e.coordinator.stopping.set()
    e.coordinator.worker()
    assert e.coordinator.job("operator", job["job_id"])["state"] == "unknown"
    assert e.backend.calls.count("apply_step") == 1


def test_missing_isolation_proof_blocks_migration(environment):
    e = environment
    e.backend.drop_proof = "no_production_credentials"
    job = e.start()
    e.coordinator.run_job(job["job_id"])
    assert e.coordinator.job("operator", job["job_id"])["state"] == "unknown"
    assert "apply_step" not in e.backend.calls


def test_cancel_before_effect_and_consumption_survives(environment):
    e = environment
    p = e.plan()
    job = e.start(p)
    e.coordinator.cancel("operator", job["job_id"], "cancel")
    e.coordinator.run_job(job["job_id"])
    assert e.coordinator.job("operator", job["job_id"])["state"] == "cancelled_safe"
    assert not e.backend.calls
    assert e.start(p, "new-key")["job_id"] == job["job_id"]


def test_revocation_stops_next_phase_without_effect_replay(environment):
    e = environment
    job = e.start()
    with e.coordinator.journal.connection() as db:
        grant = loads(
            db.execute("SELECT payload FROM jobs WHERE id=?", (job["job_id"],)).fetchone()[0]
        )["authorization_id"]
    e.coordinator.authority.revoke("operator", grant)
    e.coordinator.run_job(job["job_id"])
    assert e.coordinator.job("operator", job["job_id"])["state"] == "recovery_required"
    assert not e.backend.calls


def test_read_scope_does_not_follow_job_identity(environment):
    e = environment
    job = e.start()
    e.coordinator.authority.provision("reader", ["read"], [])
    with pytest.raises(UpdateError):
        e.coordinator.job("reader", job["job_id"])
