from typing import Literal, Protocol

from pydantic import Field, model_validator

from .errors import UpdateError
from .inventory import Observation
from .models import ID, Digest, Model, Op

READ_RESULTS = {
    "inspect",
    "validate",
    "snapshot",
    "restore_verify",
    "verify_restored_state",
    "prepare",
    "begin",
    "close_admission",
    "drain",
    "stop",
    "activate",
    "reopen_admission",
    "release",
    "restore",
}
OUTCOMES = {
    "apply_step": {"applied_verified", "not_applied", "partial_known", "unknown"},
    "initialize": {"applied_verified", "not_applied", "partial_known", "unknown"},
    "reconcile": {"not_applied", "applied_verified", "partial_known", "unknown"},
}
PROOFS = {
    "close_admission": {"admission_closed", "durable_maintenance"},
    "drain": {"work_drained", "unknown_work_absent", "writers_fenced"},
    "stop": {"writers_fenced", "maintenance_startup"},
    "snapshot": {"snapshot_consistent", "writers_fenced"},
    "restore_verify": {
        "isolated_restore",
        "no_production_credentials",
        "no_external_effects",
        "permissions_preserved",
        "domain_valid",
    },
    "apply_step": {"domain_valid", "permissions_preserved"},
    "initialize": {"empty_verified", "domain_valid", "permissions_preserved"},
    "activate": {"artifact_verified", "maintenance_startup"},
    "validate": {"domain_valid", "permissions_preserved"},
    "reopen_admission": {"admission_open", "accepted_work_reconciled"},
    "release": {"safe_lifecycle", "release_safe"},
    "restore": {"writers_fenced", "no_new_writes", "no_external_effects", "snapshot_verified"},
    "verify_restored_state": {"domain_valid", "permissions_preserved"},
}
VALID_PROOFS = set().union(*PROOFS.values())


class OwnerRequest(Model):
    contract_version: Literal[1] = 1
    operation: Op
    application_id: ID
    deployment_id: ID
    artifact_digest: Digest
    operation_id: ID
    job_id: ID
    plan_digest: Digest
    resource_ids: list[ID]
    expected_schemas: dict[str, str]
    maintenance_epochs: dict[ID, int]
    predecessor_receipts: list[ID]
    arguments: dict


class OwnerResult(Model):
    contract_version: Literal[1]
    operation: Op
    application_id: ID
    deployment_id: ID
    artifact_digest: Digest
    operation_id: ID
    outcome: Literal["verified", "applied_verified", "not_applied", "partial_known", "unknown"]
    schemas: dict[str, str]
    evidence: list[ID] = Field(min_length=1, max_length=128)
    maintenance_epochs: dict[ID, int]
    proofs: dict[str, bool]
    snapshot_digest: Digest | None = None
    observation: Observation | None = None

    @model_validator(mode="after")
    def outcomes(self):
        allowed = OUTCOMES.get(self.operation, {"verified", "unknown"})
        if (
            self.outcome not in allowed
            or not set(self.proofs) <= VALID_PROOFS
            or any(type(x) is not int or x <= 0 for x in self.maintenance_epochs.values())
        ):
            raise ValueError("operation-specific result mismatch")
        return self


class Owner(Protocol):
    def perform(self, request: OwnerRequest) -> OwnerResult: ...


def verified(request: OwnerRequest, result: OwnerResult):
    for field in (
        "operation",
        "application_id",
        "deployment_id",
        "artifact_digest",
        "operation_id",
    ):
        if getattr(request, field) != getattr(result, field):
            raise UpdateError("outcome_unknown", "Owner response identity mismatch")
    if result.outcome not in {"verified", "applied_verified"}:
        raise UpdateError("outcome_unknown" if result.outcome == "unknown" else "recovery_required")
    if any(result.proofs.get(p) is not True for p in PROOFS.get(request.operation, set())):
        raise UpdateError("outcome_unknown", "Required owner evidence is missing")
    if (
        request.operation in {"validate", "apply_step", "initialize", "verify_restored_state"}
        and result.schemas != request.expected_schemas
    ):
        raise UpdateError("recovery_required", "Owner schema result disagrees")
    if (
        request.operation in {"snapshot", "restore_verify", "restore"}
        and result.snapshot_digest is None
    ):
        raise UpdateError("backup_unverified")
    if (
        request.operation != "close_admission"
        and request.maintenance_epochs
        and result.maintenance_epochs != request.maintenance_epochs
    ):
        raise UpdateError("outcome_unknown", "Maintenance ownership changed")
