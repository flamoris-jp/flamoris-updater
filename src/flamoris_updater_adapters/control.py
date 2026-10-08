import base64

from flamoris_update_core.contracts import OwnerRequest
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Plan
from flamoris_update_core.wire import decode, digest, dumps, loads

from .journal import exclusive
from .signing import open_packet


class HostControl:
    COMMANDS = {
        "quarantine",
        "activate_authority",
        "freeze_parent",
        "transfer",
        "resolve_parent",
        "self_stage",
        "self_stop",
        "self_switch",
        "self_probe",
        "stop_coordinator",
        "epoch_evidence",
    }

    def __init__(self, host):
        self.host, self.journal = host, host.journal

    def invoke(self, packet):
        host = self.host
        host.guard()
        command = open_packet(packet, host.authorities, host.domain, "controller")
        base = {"command", "domain", "host_id", "epoch", "control_id"}
        expected = {
            "epoch_evidence": set(),
            "stop_coordinator": {"deployment_id"},
            "quarantine": {"allow_blocked"},
            "activate_authority": {"acknowledgements"},
            "freeze_parent": {"parent_job_id", "plan"},
            "transfer": {"parent_job_id", "child_job_id", "plan"},
            "resolve_parent": {"parent_job_id", "child_job_id"},
            "self_stage": {"deployment_id", "manifest_digest"},
            "self_stop": {"deployment_id"},
            "self_switch": {"deployment_id", "manifest_digest"},
            "self_probe": {"deployment_id", "manifest_digest"},
        }
        action = command.get("command")
        if (
            action not in expected
            or set(command) != base | expected[action]
            or command["domain"] != host.domain
            or command["host_id"] != host.host_id
            or type(command["epoch"]) is not int
        ):
            raise UpdateError("forbidden")
        control_id = command["control_id"]
        if not isinstance(control_id, str) or not 1 <= len(control_id) <= 128:
            raise UpdateError("invalid_input")
        binding = digest(dumps(command))
        with exclusive(self.journal.directory / "executor.lock"):
            old = self.journal.get("control", control_id)
            if old:
                if old["binding"] != binding:
                    raise UpdateError("operation_conflict")
                if old["outcome"] != "verified":
                    raise UpdateError("outcome_unknown")
                return old["receipt"]
            current = int(self.journal.meta("epoch"))
            if action == "quarantine":
                if command["epoch"] != current + 1 or type(command["allow_blocked"]) is not bool:
                    raise UpdateError("stale_authority")
            elif command["epoch"] != current:
                raise UpdateError("stale_authority")
            with self.journal.transaction() as db:
                self.journal.put(
                    "control",
                    control_id,
                    {"binding": binding, "command": action, "outcome": "intent"},
                    db,
                )
                self.journal.event(db, "control_intent", control_id)
            self.journal.flush_export()
            try:
                evidence = self._perform(command)
                response = host.signer.packet(
                    {
                        "control_version": 1,
                        "control_id": control_id,
                        "host_id": host.host_id,
                        "domain": host.domain,
                        "epoch": command["epoch"],
                        "command": action,
                        "evidence": evidence,
                    }
                )
                with self.journal.transaction() as db:
                    self.journal.put(
                        "control",
                        control_id,
                        {
                            "binding": binding,
                            "command": action,
                            "outcome": "verified",
                            "receipt": response,
                        },
                        db,
                    )
                    self.journal.event(db, "control_confirmed", control_id)
                self.journal.flush_export()
                return response
            except BaseException:
                with self.journal.transaction() as db:
                    self.journal.put(
                        "control",
                        control_id,
                        {"binding": binding, "command": action, "outcome": "unknown"},
                        db,
                    )
                    self.journal.event(db, "control_unknown", control_id)
                raise

    def _perform(self, command):
        h, j, action = self.host, self.journal, command["command"]
        if action == "epoch_evidence":
            if j.meta("mode") != "maintenance":
                raise UpdateError("outcome_unknown")
            return {"mode": "maintenance"}
        if action == "quarantine":
            with j.transaction() as db:
                if (
                    not command["allow_blocked"]
                    and db.execute("SELECT 1 FROM claims LIMIT 1").fetchone()
                ):
                    raise UpdateError("busy")
                db.execute("UPDATE meta SET value=? WHERE key='epoch'", (str(command["epoch"]),))
                db.execute("UPDATE meta SET value='maintenance' WHERE key='mode'")
            return {"mode": "maintenance"}
        if action == "activate_authority":
            packets = command["acknowledgements"]
            if not isinstance(packets, dict) or set(packets) != set(h.receipt_keys):
                raise UpdateError(
                    "outcome_unknown", "Every configured host must acknowledge the new epoch"
                )
            for identity, packet in packets.items():
                if packet.get("signature", {}).get("key_id") != identity:
                    raise UpdateError("forbidden")
                obj = open_packet(packet, h.receipt_keys, h.domain, "receipt")
                if (
                    obj.get("host_id") != identity
                    or obj.get("domain") != h.domain
                    or obj.get("epoch") != command["epoch"]
                    or obj.get("command") not in {"quarantine", "epoch_evidence"}
                    or obj.get("evidence") != {"mode": "maintenance"}
                ):
                    raise UpdateError("outcome_unknown")
            with j.transaction() as db:
                db.execute("UPDATE meta SET value='active' WHERE key='mode'")
            return {"mode": "active"}
        if action in {"self_stage", "self_stop", "self_switch", "self_probe", "stop_coordinator"}:
            profile = h.profiles.get(command["deployment_id"])
            if (
                profile is None
                or profile.role not in {"coordinator", "executor"}
                or profile.artifact_kind != "native"
            ):
                raise UpdateError("protected_target")
            if action == "stop_coordinator" and profile.role != "coordinator":
                raise UpdateError("forbidden")
            with j.connection() as db:
                if (
                    action != "stop_coordinator"
                    and db.execute("SELECT 1 FROM claims LIMIT 1").fetchone()
                ):
                    raise UpdateError("busy")
            driver = h.backend.drivers[profile.id]
            if action in {"self_stop", "stop_coordinator"}:
                driver.stop()
                return {"stopped": True}
            manifest = h.releases.get(command["manifest_digest"]).select(
                profile.platform, profile.artifact_kind
            )
            if (
                manifest.application_id != profile.application_id
                or manifest.artifact.kind != "native"
                or manifest.artifact.platform != profile.platform
                or manifest.migrations
                or manifest.schema_targets != {"control": "updater-control-1"}
            ):
                raise UpdateError("unsupported_journal")
            if action == "self_stage":
                driver.prepare(manifest)
                from .compatibility import bundle_metadata

                metadata = bundle_metadata(
                    driver.store.root / manifest.artifact.digest.removeprefix("sha256:")
                )
                if metadata["version"] != manifest.release:
                    raise UpdateError("unsupported_journal")
                return metadata
            if action == "self_probe":
                from .compatibility import probe_candidate

                binding = getattr(driver, "control_state_directory", None)
                if binding is None or getattr(driver, "python_executable", None) is None:
                    raise UpdateError("invalid_profile")
                return probe_candidate(
                    driver.store.root / manifest.artifact.digest.removeprefix("sha256:"),
                    binding,
                    driver.command,
                    driver.python_executable,
                )
            driver.activate(manifest, command["control_id"])
            return {"activated": manifest.release, "manifest_digest": command["manifest_digest"]}
        if action == "freeze_parent":
            plan = decode(Plan, base64.b64decode(command["plan"], validate=True))
            parent = command["parent_job_id"]
            saved = j.get("host_plan", parent)
            if saved and saved["plan_digest"] != digest(
                base64.b64decode(command["plan"], validate=True)
            ):
                raise UpdateError("operation_conflict")
            local = {s.deployment_id for s in plan.steps if s.host_id == h.host_id}
            evidence = {}
            for identity in local:
                profile = h.profiles[identity]
                if (
                    profile.role != "application"
                    or digest(dumps(profile)) != plan.profile_digests[identity]
                ):
                    raise UpdateError("forbidden")
                manifest = h.releases.get(plan.targets[identity], eligible=False).select(
                    profile.platform, profile.artifact_kind
                )
                epochs = {
                    r: (j.get("maintenance", r) or {}).get("epoch", 0)
                    for r in profile.resources.values()
                }
                if any(not x for x in epochs.values()):
                    # No data effects occurred if every local operation was only prepare/begin.
                    with j.connection() as db:
                        rows = db.execute(
                            "SELECT payload,outcome FROM operations WHERE job_id=?", (parent,)
                        ).fetchall()
                    if any(
                        next(
                            s for s in plan.steps if s.id == loads(r["payload"])["step_id"]
                        ).operation
                        not in {"prepare", "begin"}
                        or r["outcome"] not in {"verified", "applied_verified"}
                        for r in rows
                    ):
                        raise UpdateError("outcome_unknown")
                request = OwnerRequest(
                    operation="reconcile",
                    application_id=profile.application_id,
                    deployment_id=identity,
                    artifact_digest=manifest.artifact.digest,
                    operation_id=command["control_id"] + "." + identity,
                    job_id=parent,
                    plan_digest=digest(base64.b64decode(command["plan"])),
                    resource_ids=sorted(profile.resources.values()),
                    expected_schemas=h.backend.inspect(profile).schemas,
                    maintenance_epochs={r: e for r, e in epochs.items() if e},
                    predecessor_receipts=[],
                    arguments={"freeze": True, "parent_job_id": parent},
                )
                result = h.backend.perform(profile, manifest, request)
                if (
                    result.outcome not in {"not_applied", "applied_verified", "partial_known"}
                    or any(
                        result.proofs.get(p) is not True
                        for p in {"writers_fenced", "unknown_work_absent", "durable_maintenance"}
                    )
                    or result.operation_id != request.operation_id
                    or result.deployment_id != identity
                    or result.application_id != profile.application_id
                    or result.artifact_digest != manifest.artifact.digest
                ):
                    raise UpdateError("outcome_unknown")
                observed = h.backend.inspect(profile)
                if observed.active_work or observed.unknown_work:
                    raise UpdateError("outcome_unknown")
                evidence[identity] = {
                    "schemas": observed.schemas,
                    "evidence": result.evidence,
                    "maintenance_epochs": result.maintenance_epochs,
                }
            with j.transaction() as db:
                j.put(
                    "frozen_parent",
                    parent,
                    {
                        "plan_digest": digest(base64.b64decode(command["plan"])),
                        "evidence": evidence,
                        "child_job_id": None,
                    },
                    db,
                )
            return {"frozen": True, "parent_job_id": parent, "deployments": evidence}
        parent, child = command["parent_job_id"], command["child_job_id"]
        frozen = j.get("frozen_parent", parent)
        if not frozen:
            raise UpdateError("outcome_unknown")
        if action == "transfer":
            plan = decode(Plan, base64.b64decode(command["plan"], validate=True))
            if (
                plan.action != "recover"
                or plan.parent_job_id != parent
                or plan.coordinator_epoch != command["epoch"]
                or frozen["child_job_id"] not in {None, child}
            ):
                raise UpdateError("forbidden")
            with j.transaction() as db:
                rows = db.execute("SELECT kind,id FROM claims WHERE job_id=?", (parent,)).fetchall()
                if any(
                    (r["kind"] == "resource" and r["id"] not in plan.resources)
                    or (r["kind"] == "host" and r["id"] not in plan.hosts)
                    for r in rows
                ):
                    raise UpdateError("forbidden")
                db.execute("UPDATE claims SET job_id=? WHERE job_id=?", (child, parent))
                j.put(
                    "frozen_parent",
                    parent,
                    {**frozen, "child_job_id": child},
                    db,
                    expected=frozen["_revision"],
                )
            return {"transferred": True, "parent_job_id": parent, "child_job_id": child}
        if frozen["child_job_id"] != child:
            raise UpdateError("forbidden")
        with j.connection() as db:
            if db.execute("SELECT 1 FROM claims WHERE job_id IN (?,?)", (parent, child)).fetchone():
                raise UpdateError("outcome_unknown")
        with j.transaction() as db:
            j.put("parent_resolution", parent, {"child_job_id": child, "resolved": True}, db)
        return {"resolved": True, "parent_job_id": parent, "child_job_id": child}
