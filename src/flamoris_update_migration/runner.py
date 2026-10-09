"""Standalone application-owned migration runner. No Coordinator, MCP or Web dependency."""

import argparse
import importlib
import sys
from typing import Protocol

from flamoris_update_core.contracts import PROOFS, OwnerRequest, OwnerResult
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.journal import exclusive
from flamoris_update_core.wire import decode, digest, dumps


class Application(Protocol):
    def inspect(self): ...
    def fenced(self, request: OwnerRequest) -> bool: ...
    def empty_verified(self, request: OwnerRequest) -> bool: ...
    def validate(self, request: OwnerRequest) -> dict[str, bool]: ...
    def reconcile(self, request: OwnerRequest) -> OwnerResult: ...


class MigrationRunner:
    def __init__(self, journal, manifest, profile, application: Application, handlers: dict):
        self.journal, self.manifest, self.profile, self.application, self.handlers = (
            journal,
            manifest,
            profile,
            application,
            handlers,
        )

    def invoke(self, request: OwnerRequest) -> OwnerResult:
        m, p, r = self.manifest, self.profile, request
        if (
            r.operation not in {"apply_step", "initialize", "reconcile"}
            or r.application_id != m.application_id
            or r.application_id != p.application_id
            or r.deployment_id != p.id
            or r.artifact_digest != m.artifact.digest
            or set(r.resource_ids) != set(p.resources.values())
            or not self.application.fenced(r)
        ):
            raise UpdateError("forbidden")
        binding = digest(dumps(r))
        with exclusive(self.journal.directory / "migration.lock"):
            old = self.journal.get("migration_operation", r.operation_id)
            if old:
                if old["binding"] != binding:
                    raise UpdateError("operation_conflict")
                if old["result"] is None:
                    raise UpdateError("outcome_unknown")
                return decode(OwnerResult, dumps(old["result"]))
            if r.operation == "reconcile":
                result = self.application.reconcile(r)
                if (
                    result.operation_id != r.operation_id
                    or result.deployment_id != r.deployment_id
                    or result.application_id != r.application_id
                    or result.artifact_digest != r.artifact_digest
                    or result.operation != "reconcile"
                ):
                    raise UpdateError("outcome_unknown")
                with self.journal.transaction() as db:
                    self.journal.put(
                        "migration_operation",
                        r.operation_id,
                        {"binding": binding, "result": result.model_dump()},
                        db,
                    )
                return result
            arguments = {k: v for k, v in r.arguments.items() if k != "read_only"}
            observed = self.application.inspect()
            if (
                observed.active_work
                or observed.unknown_work
                or observed.resource_bindings != p.resources
            ):
                raise UpdateError("busy")
            if r.operation == "apply_step":
                edges = [e for e in m.migrations if e.model_dump(by_alias=True) == arguments]
                if len(edges) != 1:
                    raise UpdateError("unsupported_migration")
                edge = edges[0]
                if (
                    edge.runner_profile not in p.runner_profiles
                    or any(
                        observed.schemas.get(k) != v
                        for k, v in {**edge.source, **edge.requires}.items()
                    )
                    or r.expected_schemas != {**observed.schemas, **edge.to}
                ):
                    raise UpdateError("unsupported_migration")
                handler = edge.handler_id
            else:
                if (
                    not m.initialization.supported
                    or arguments != m.initialization.model_dump(exclude_none=True)
                    or r.expected_schemas != m.schema_targets
                    or observed.schemas
                    or set(observed.absent_resources) != set(p.resources.values())
                    or not self.application.empty_verified(r)
                    or m.initialization.runner_profile not in p.runner_profiles
                ):
                    raise UpdateError("not_empty")
                handler = m.initialization.handler_id
            if handler not in self.handlers:
                raise UpdateError("unsupported_migration")
            with self.journal.transaction() as db:
                self.journal.put(
                    "migration_operation", r.operation_id, {"binding": binding, "result": None}, db
                )
                self.journal.event(db, "migration_intent", r.operation_id)
            self.journal.flush_export()
            try:
                self.handlers[handler](r)
                actual = self.application.inspect()
                proofs = self.application.validate(r)
                if (
                    actual.schemas != r.expected_schemas
                    or actual.unknown_work
                    or any(proofs.get(k) is not True for k in PROOFS[r.operation])
                ):
                    raise UpdateError("recovery_required")
                result = OwnerResult(
                    contract_version=1,
                    operation=r.operation,
                    application_id=r.application_id,
                    deployment_id=r.deployment_id,
                    artifact_digest=r.artifact_digest,
                    operation_id=r.operation_id,
                    outcome="applied_verified",
                    schemas=actual.schemas,
                    evidence=actual.evidence,
                    maintenance_epochs=r.maintenance_epochs,
                    proofs=proofs,
                )
                with self.journal.transaction() as db:
                    self.journal.put(
                        "migration_operation",
                        r.operation_id,
                        {"binding": binding, "result": result.model_dump()},
                        db,
                    )
                    self.journal.event(db, "migration_result", r.operation_id, "applied_verified")
                self.journal.flush_export()
                return result
            except BaseException:
                # Intent is the tombstone. Application reconciliation is a separate scoped operation.
                raise UpdateError(
                    "outcome_unknown", "Inspect application-owned effects; never replay this intent"
                ) from None


def main():
    parser = argparse.ArgumentParser(
        description="Standalone signed-bundle application migration entry"
    )
    parser.add_argument(
        "--factory-module",
        required=True,
        help="Application-owned installed module; never a remote tool argument",
    )
    args = parser.parse_args()
    try:
        request = decode(OwnerRequest, sys.stdin.buffer.read(1024 * 1024 + 1))
        runner = importlib.import_module(args.factory_module).create_runner()
        if not isinstance(runner, MigrationRunner):
            raise UpdateError("invalid_profile")
        result = runner.invoke(request)
        sys.stdout.buffer.write(dumps(result) + b"\n")
    except Exception as error:
        sys.stdout.buffer.write(
            dumps(
                error.public() if isinstance(error, UpdateError) else {"error": "outcome_unknown"}
            )
            + b"\n"
        )
        raise SystemExit(1) from None
