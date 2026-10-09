import base64
from typing import Protocol

from flamoris_update_core.contracts import OwnerRequest, OwnerResult, verified
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.execution_graph import validate_execution_graph
from flamoris_update_core.inventory import DeploymentProfile, Observation, fingerprint
from flamoris_update_core.models import Manifest, Plan, Step
from flamoris_update_core.wire import decode, digest, dumps, loads

from .journal import Journal, exclusive
from .signing import Key, Signer, open_packet


class Backend(Protocol):
    def inspect(self, profile: DeploymentProfile) -> Observation: ...
    def prepare(self, profile: DeploymentProfile, manifest: Manifest): ...
    def perform(
        self, profile: DeploymentProfile, manifest: Manifest, request: OwnerRequest
    ) -> OwnerResult: ...


def receipt(
    packet: dict, keys: dict[str, Key], domain: str, job: str, plan_digest: str, step: Step
) -> dict:
    if packet.get("signature", {}).get("key_id") != step.host_id:
        raise UpdateError("outcome_unknown", "Receipt came from another host")
    obj = open_packet(packet, keys, domain, "receipt")
    if (
        set(obj)
        != {
            "receipt_version",
            "host_id",
            "job_id",
            "plan_digest",
            "step_id",
            "operation_id",
            "result",
        }
        or type(obj["receipt_version"]) is not int
        or obj["receipt_version"] != 1
        or obj["host_id"] != step.host_id
        or obj["job_id"] != job
        or obj["plan_digest"] != plan_digest
        or obj["step_id"] != step.id
    ):
        raise UpdateError("outcome_unknown", "Receipt binding disagrees")
    result = decode(OwnerResult, dumps(obj["result"]), 256 * 1024)
    if (
        result.operation != step.operation
        or result.operation_id != obj["operation_id"]
        or result.deployment_id != step.deployment_id
        or result.outcome not in {"verified", "applied_verified"}
    ):
        raise UpdateError("outcome_unknown")
    return obj


class HostExecutor:
    def __init__(
        self,
        host_id: str,
        domain: str,
        journal: Journal,
        profiles: dict[str, DeploymentProfile],
        releases,
        backend: Backend,
        signer: Signer,
        authorities: dict[str, Key],
        receipt_keys: dict[str, Key],
        clock,
        resources=None,
    ):
        self.host_id, self.domain, self.journal = host_id, domain, journal
        self.resources = resources
        self.profiles, self.releases, self.backend = profiles, releases, backend
        self.guard = lambda: None
        self.signer, self.authorities, self.receipt_keys, self.clock = (
            signer,
            authorities,
            receipt_keys,
            clock,
        )

    def inspect(self, identity: str) -> Observation:
        self.guard()
        profile = self.profiles.get(identity)
        if profile is None or profile.host_id != self.host_id:
            raise UpdateError("forbidden")
        observed = self.backend.inspect(profile)
        if self.resources is not None and observed.physical_binding_digests != {
            r: self.resources[r].physical_binding_digest for r in profile.resources.values()
        }:
            raise UpdateError("invalid_profile")
        observed = observed.model_copy(update={"observed_at": self.clock()})
        with self.journal.connection() as db:
            unresolved = db.execute(
                "SELECT job_id FROM operations WHERE outcome IN ('intent','unknown','partial_known')"
            ).fetchall()
        if any(not self.journal.get("frozen_parent", row[0]) for row in unresolved):
            return observed.model_copy(update={"unknown_work": True})
        return observed

    def outcome(self, operation_id: str) -> dict:
        with self.journal.connection() as db:
            row = db.execute(
                "SELECT outcome,result FROM operations WHERE id=?", (operation_id,)
            ).fetchone()
            if row is None:
                return {"outcome": "not_admitted"}
            return {
                "outcome": row["outcome"],
                "receipt": loads(row["result"]) if row["result"] else None,
            }

    def abort(self, packet: dict) -> dict:
        command = open_packet(packet, self.authorities, self.domain, "authority")
        if (
            set(command) != {"command", "domain", "host_id", "epoch", "job_id"}
            or command["command"] != "abort_preparation"
            or command["domain"] != self.domain
            or command["host_id"] != self.host_id
            or command["epoch"] != int(self.journal.meta("epoch"))
        ):
            raise UpdateError("forbidden")
        job_id = command["job_id"]
        with exclusive(self.journal.directory / "executor.lock"):
            with self.journal.transaction() as db:
                previous = self.journal.get("aborted", job_id, db)
                if previous:
                    return previous["packet"]
                rows = db.execute(
                    "SELECT payload,outcome FROM operations WHERE job_id=?", (job_id,)
                ).fetchall()
                for row in rows:
                    if row["outcome"] not in {"verified", "applied_verified"}:
                        raise UpdateError("outcome_unknown")
                    ticket = loads(row["payload"])
                    plan = decode(Plan, base64.b64decode(ticket["plan"]))
                    step = next(s for s in plan.steps if s.id == ticket["step_id"])
                    if step.operation not in {"prepare", "begin"}:
                        raise UpdateError("recovery_required")
                db.execute("DELETE FROM claims WHERE job_id=?", (job_id,))
                response = self.signer.packet(
                    {"command": "preparation_aborted", "job_id": job_id, "host_id": self.host_id}
                )
                self.journal.put("aborted", job_id, {"packet": response}, db)
                self.journal.event(db, "preparation_aborted", job_id)
            self.journal.flush_export()
            return response

    def run(self, packet: dict) -> dict:
        self.guard()
        purpose = (
            "controller"
            if packet.get("signature", {}).get("key_id")
            in {k for k, v in self.authorities.items() if v.purpose == "controller"}
            else "authority"
        )
        ticket = open_packet(packet, self.authorities, self.domain, purpose)
        if (
            set(ticket)
            != {
                "ticket_version",
                "domain",
                "host_id",
                "epoch",
                "admitted_at",
                "job_id",
                "plan",
                "step_id",
                "predecessors",
            }
            or type(ticket["ticket_version"]) is not int
            or ticket["ticket_version"] != 1
            or ticket["domain"] != self.domain
            or ticket["host_id"] != self.host_id
        ):
            raise UpdateError("invalid_input")
        try:
            plan_raw = base64.b64decode(ticket["plan"], validate=True)
        except (ValueError, TypeError):
            raise UpdateError("invalid_input") from None
        plan = decode(Plan, plan_raw)
        validate_execution_graph(plan)
        plan_digest = digest(plan_raw)
        if (
            type(ticket["epoch"]) is not int
            or ticket["epoch"] != int(self.journal.meta("epoch"))
            or ticket["epoch"] != plan.coordinator_epoch
            or not plan.created_at <= ticket["admitted_at"] <= plan.expires_at
            or ticket["admitted_at"] > self.clock() + 30
        ):
            raise UpdateError("stale_authority")
        step = next((s for s in plan.steps if s.id == ticket["step_id"]), None)
        if (
            step is None
            or step.host_id != self.host_id
            or set(ticket["predecessors"]) != set(step.predecessors)
        ):
            raise UpdateError("invalid_input")
        profile = self.profiles.get(step.deployment_id)
        if (
            profile is None
            or profile.role != "application"
            or step.operation not in profile.operations
            or plan.profile_digests[profile.id] != digest(dumps(profile))
            or set(step.resources)
            != {
                r
                for r in profile.resources.values()
                if step.operation
                not in {"snapshot", "restore_verify", "restore", "verify_restored_state"}
                or self.resources is None
                or self.resources[r].owner_deployment == profile.id
            }
        ):
            raise UpdateError("forbidden")
        if (
            self.resources is not None
            and step.operation in {"snapshot", "restore_verify", "restore", "verify_restored_state"}
            and any(self.resources[r].owner_deployment != profile.id for r in step.resources)
        ):
            raise UpdateError("forbidden")
        if plan.action == "recover" and purpose != "controller":
            raise UpdateError("forbidden")
        if plan.action not in {"update", "install", "verify_recovery", "recover"}:
            raise UpdateError("protected_target")
        read_only = plan.action == "verify_recovery"
        if read_only and step.operation not in {"prepare", "validate", "release"}:
            raise UpdateError("forbidden")
        if plan.action == "verify_recovery" and not plan.parent_job_id:
            raise UpdateError("invalid_input")
        group_epochs = {}
        for predecessor_id, predecessor in ticket["predecessors"].items():
            predecessor_step = next(s for s in plan.steps if s.id == predecessor_id)
            confirmed = receipt(
                predecessor,
                self.receipt_keys,
                self.domain,
                ticket["job_id"],
                plan_digest,
                predecessor_step,
            )
            for resource_id, epoch in confirmed["result"]["maintenance_epochs"].items():
                if resource_id in group_epochs and group_epochs[resource_id] != epoch:
                    raise UpdateError(
                        "outcome_unknown", "Shared resource maintenance epochs disagree"
                    )
                group_epochs[resource_id] = epoch
        manifest = self.releases.get(
            plan.targets[profile.id], eligible=step.operation in {"prepare", "activate"}
        ).select(profile.platform, profile.artifact_kind)
        if manifest.application_id != profile.application_id:
            raise UpdateError("forbidden")
        operation_id = ticket["job_id"] + "." + step.id
        binding = digest(
            dumps(
                {
                    "job_id": ticket["job_id"],
                    "plan_digest": plan_digest,
                    "step": step.model_dump(),
                    "epoch": ticket["epoch"],
                    "predecessors": {
                        k: digest(dumps(v)) for k, v in ticket["predecessors"].items()
                    },
                }
            )
        )
        with exclusive(self.journal.directory / "executor.lock"):
            with self.journal.transaction() as db:
                existing = db.execute(
                    "SELECT binding FROM operations WHERE id=?", (operation_id,)
                ).fetchone()
                if existing:
                    if existing[0] != binding:
                        raise UpdateError("operation_conflict")
                    return self.outcome(operation_id)
                if self.journal.get("frozen_parent", ticket["job_id"], db):
                    raise UpdateError("recovery_required", "Frozen parent operations cannot resume")
                if self.journal.meta("mode", db) != "active":
                    raise UpdateError("busy")
                # A read-only child cannot claim a blocked parent's mutation rights.
                if read_only:
                    unsettled = db.execute(
                        "SELECT 1 FROM operations WHERE job_id=? AND outcome IN ('intent','unknown','partial_known') LIMIT 1",
                        (plan.parent_job_id or "",),
                    ).fetchone()
                    if unsettled and not self.journal.get(
                        "frozen_parent", plan.parent_job_id or "", db
                    ):
                        raise UpdateError("outcome_unknown")
                if step.operation == "prepare":
                    if not read_only:
                        for kind, identity in [("host", self.host_id)] + [
                            ("resource", r) for r in step.resources
                        ]:
                            old = db.execute(
                                "SELECT job_id FROM claims WHERE kind=? AND id=?", (kind, identity)
                            ).fetchone()
                            if old and old[0] != ticket["job_id"]:
                                raise UpdateError("busy")
                            db.execute(
                                "INSERT OR IGNORE INTO claims VALUES(?,?,?)",
                                (kind, identity, ticket["job_id"]),
                            )
                    self.journal.put(
                        "host_plan",
                        ticket["job_id"],
                        {
                            "plan_digest": plan_digest,
                            "admitted_at": ticket["admitted_at"],
                            "plan": ticket["plan"],
                        },
                        db,
                    )
                elif (self.journal.get("host_plan", ticket["job_id"], db) or {}).get(
                    "plan_digest"
                ) != plan_digest:
                    raise UpdateError("forbidden", "Local preparation is not confirmed")
                db.execute(
                    "INSERT INTO operations VALUES(?,?,?,?,?,NULL)",
                    (operation_id, ticket["job_id"], binding, dumps(ticket), "intent"),
                )
                self.journal.event(db, "operation_intent", operation_id)
            # Export failure leaves durable intent and prevents the physical effect.
            self.journal.flush_export()
            try:
                result = self._perform(
                    plan,
                    step,
                    manifest,
                    profile,
                    ticket["job_id"],
                    operation_id,
                    plan_digest,
                    read_only,
                )
                response = self.signer.packet(
                    {
                        "receipt_version": 1,
                        "host_id": self.host_id,
                        "job_id": ticket["job_id"],
                        "plan_digest": plan_digest,
                        "step_id": step.id,
                        "operation_id": operation_id,
                        "result": result.model_dump(),
                    }
                )
                with self.journal.transaction() as db:
                    if step.operation == "close_admission":
                        if set(result.maintenance_epochs) != set(step.resources):
                            raise UpdateError("outcome_unknown")
                        for resource_id, epoch in result.maintenance_epochs.items():
                            previous = self.journal.get("maintenance", resource_id, db)
                            if previous and (
                                (
                                    previous["job_id"] == ticket["job_id"]
                                    and previous["epoch"] != epoch
                                )
                                or (
                                    previous["job_id"] != ticket["job_id"]
                                    and previous["epoch"] >= epoch
                                )
                            ):
                                raise UpdateError("outcome_unknown")
                            self.journal.put(
                                "maintenance",
                                resource_id,
                                {"job_id": ticket["job_id"], "epoch": epoch},
                                db,
                            )
                    if step.operation == "release" and not read_only:
                        # Keep shared local claims until every local participant finalized.
                        required = [
                            s
                            for s in plan.steps
                            if s.host_id == self.host_id and s.operation == "release"
                        ]
                        done = all(
                            s.id == step.id
                            or db.execute(
                                "SELECT 1 FROM operations WHERE id=? AND outcome IN ('verified','applied_verified')",
                                (ticket["job_id"] + "." + s.id,),
                            ).fetchone()
                            for s in required
                        )
                        if done:
                            db.execute("DELETE FROM claims WHERE job_id=?", (ticket["job_id"],))
                    db.execute(
                        "UPDATE operations SET outcome=?,result=? WHERE id=?",
                        (result.outcome, dumps(response), operation_id),
                    )
                    self.journal.event(db, "operation_result", operation_id, result.outcome)
                self.journal.flush_export()
                return {"outcome": result.outcome, "receipt": response}
            except Exception:
                with self.journal.transaction() as db:
                    db.execute(
                        "UPDATE operations SET outcome='unknown' WHERE id=? AND outcome='intent'",
                        (operation_id,),
                    )
                    self.journal.event(db, "operation_result", operation_id, "unknown")
                raise UpdateError(
                    "outcome_unknown",
                    "Inspect durable operation and owner evidence before continuing",
                ) from None

    def _perform(self, plan, step, manifest, profile, job_id, operation_id, plan_digest, read_only):
        observed = self.backend.inspect(profile)
        if observed.resource_bindings != profile.resources or (
            self.resources is not None
            and observed.physical_binding_digests
            != {r: self.resources[r].physical_binding_digest for r in profile.resources.values()}
        ):
            raise UpdateError("stale_plan")
        if step.operation == "prepare":
            if fingerprint(observed) != plan.observations[profile.id]:
                raise UpdateError("stale_plan")
            if not read_only:
                self.backend.prepare(profile, manifest)
        epochs = {}
        for r in step.resources:
            maintenance = self.journal.get("maintenance", r)
            if maintenance and maintenance["job_id"] in {
                job_id,
                plan.parent_job_id if read_only else None,
            }:
                epochs[r] = maintenance["epoch"]
        if (
            not read_only
            and step.operation not in {"prepare", "begin", "close_admission"}
            and set(epochs) != set(step.resources)
        ):
            raise UpdateError("outcome_unknown")
        schemas = dict(observed.schemas)
        if step.operation == "apply_step":
            if any(
                schemas.get(k) != v
                for k, v in {**step.arguments["from"], **step.arguments["requires"]}.items()
            ):
                raise UpdateError("stale_plan")
            schemas.update(step.arguments["to"])
        elif step.operation in {"validate", "initialize", "restore", "verify_restored_state"}:
            schemas = manifest.schema_targets
        if step.operation == "prepare" or (step.operation in {"begin", "release"} and read_only):
            return OwnerResult(
                contract_version=1,
                operation=step.operation,
                application_id=profile.application_id,
                deployment_id=profile.id,
                artifact_digest=manifest.artifact.digest,
                operation_id=operation_id,
                outcome="verified",
                schemas=schemas,
                evidence=observed.evidence,
                maintenance_epochs=epochs,
                proofs={},
            )
        request = OwnerRequest(
            operation=step.operation,
            application_id=profile.application_id,
            deployment_id=profile.id,
            artifact_digest=manifest.artifact.digest,
            operation_id=operation_id,
            job_id=job_id,
            plan_digest=plan_digest,
            resource_ids=step.resources,
            expected_schemas=schemas,
            maintenance_epochs=epochs,
            predecessor_receipts=step.predecessors,
            arguments={
                **step.arguments,
                "read_only": read_only,
                "manifest_digest": plan.targets[profile.id],
            },
        )
        result = self.backend.perform(profile, manifest, request)
        verified(request, result)
        if step.operation == "restore_verify":
            with self.journal.connection() as db:
                snapshots = [
                    loads(r[0])
                    for r in db.execute(
                        "SELECT result FROM operations WHERE job_id=? AND outcome='verified' AND result IS NOT NULL",
                        (job_id,),
                    )
                ]
            expected = [
                open_packet(x, self.receipt_keys, self.domain, "receipt")["result"].get(
                    "snapshot_digest"
                )
                for x in snapshots
                if open_packet(x, self.receipt_keys, self.domain, "receipt")["result"]["operation"]
                == "snapshot"
                and open_packet(x, self.receipt_keys, self.domain, "receipt")["result"][
                    "deployment_id"
                ]
                == profile.id
            ]
            if result.snapshot_digest not in expected:
                raise UpdateError("backup_unverified")
        if step.operation == "restore":
            parent = plan.parent_job_id
            frozen = self.journal.get("frozen_parent", parent)
            with self.journal.connection() as db:
                packets = [
                    loads(row[0])
                    for row in db.execute(
                        "SELECT result FROM operations WHERE job_id=? AND result IS NOT NULL AND outcome='verified'",
                        (parent,),
                    )
                ]
            snapshots = [
                open_packet(packet, self.receipt_keys, self.domain, "receipt") for packet in packets
            ]
            if (
                not frozen
                or result.snapshot_digest != step.arguments.get("snapshot_digest")
                or not any(
                    s["job_id"] == parent
                    and s["plan_digest"] == frozen["plan_digest"]
                    and s["result"]["operation"] == "snapshot"
                    and s["result"]["deployment_id"] == profile.id
                    and s["result"]["snapshot_digest"] == result.snapshot_digest
                    for s in snapshots
                )
            ):
                raise UpdateError("backup_unverified")
        return result
