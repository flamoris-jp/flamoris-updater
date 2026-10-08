import base64
import uuid

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps, loads

from .journal import exclusive
from .signing import open_packet


class RecoveryController:
    """Stable local controller owns takeover, linked recovery and protected native handoff."""

    def __init__(self, coordinator, signer, control_deployment_id, current_manifest, readiness):
        self.c, self.j, self.signer = coordinator, coordinator.journal, signer
        self.target, self.current_manifest, self.readiness = (
            control_deployment_id,
            current_manifest,
            readiness,
        )
        if coordinator.profiles[control_deployment_id].role != "coordinator":
            raise UpdateError("invalid_profile")
        self.c.signer = signer

    def _call(self, host_id, action, identity, epoch=None, **arguments):
        identity = "ctl-" + digest(identity.encode()).removeprefix("sha256:")[:48]
        epoch = epoch if epoch is not None else int(self.j.meta("epoch"))
        packet = self.signer.packet(
            {
                "command": action,
                "domain": self.c.domain,
                "host_id": host_id,
                "epoch": epoch,
                "control_id": identity,
                **arguments,
            }
        )
        host = self.c.hosts[host_id]
        response = host.protected(packet)
        if response.get("signature", {}).get("key_id") != host_id:
            raise UpdateError("outcome_unknown")
        evidence = open_packet(response, self.c.receipt_keys, self.c.domain, "receipt")
        if (
            evidence.get("host_id") != host_id
            or evidence.get("domain") != self.c.domain
            or evidence.get("epoch") != epoch
            or evidence.get("command") != action
            or evidence.get("control_id") != identity
        ):
            raise UpdateError("outcome_unknown")
        with self.j.transaction() as db:
            self.j.put("controller_receipt", identity, {"packet": response}, db)
        return response, evidence["evidence"]

    def _control(self, action, identity, **arguments):
        profile = self.c.profiles[self.target]
        return self._call(profile.host_id, action, identity, deployment_id=self.target, **arguments)

    def gate(self, identity, allow_blocked):
        with self.j.transaction() as db:
            if not allow_blocked and db.execute("SELECT 1 FROM claims LIMIT 1").fetchone():
                raise UpdateError("busy")
            if db.execute(
                "SELECT 1 FROM jobs WHERE state NOT IN ('succeeded','failed_safe','cancelled_safe','unknown','recovery_required') LIMIT 1"
            ).fetchone():
                raise UpdateError("busy")
            db.execute("UPDATE meta SET value='recovery' WHERE key='mode'")
            self.j.event(db, "domain_gated", identity)
        self.j.flush_export()
        self._control("stop_coordinator", identity + "-stop-" + self.j.meta("epoch"))

    def advance_epoch(self, identity, allow_blocked):
        saved = self.j.get("epoch_handoff", identity)
        if saved is None:
            saved = {
                "epoch": int(self.j.meta("epoch")) + 1,
                "allow_blocked": allow_blocked,
                "acks": {},
                "active": {},
            }
            with self.j.transaction() as db:
                self.j.put("epoch_handoff", identity, saved, db)
                self.j.event(db, "epoch_handoff_intent", identity)
            self.j.flush_export()
        elif saved["allow_blocked"] != allow_blocked:
            raise UpdateError("operation_conflict")
        epoch = saved["epoch"]
        for host_id in sorted(self.c.hosts):
            if host_id in saved["acks"]:
                continue
            try:
                packet, _ = self._call(
                    host_id,
                    "quarantine",
                    identity + "-q-" + host_id,
                    epoch,
                    allow_blocked=allow_blocked,
                )
            except UpdateError as error:
                if error.code != "outcome_unknown":
                    raise
                # Independent metadata inspection can confirm a committed epoch after reply/process loss.
                packet, _ = self._call(host_id, "epoch_evidence", identity + "-e-" + host_id, epoch)
            saved["acks"][host_id] = packet
            with self.j.transaction() as db:
                self.j.put("epoch_handoff", identity, saved, db)
        for host_id in sorted(self.c.hosts):
            if host_id in saved["active"]:
                continue
            packet, _ = self._call(
                host_id,
                "activate_authority",
                identity + "-a-" + host_id,
                epoch,
                acknowledgements=saved["acks"],
            )
            saved["active"][host_id] = packet
            with self.j.transaction() as db:
                self.j.put("epoch_handoff", identity, saved, db)
        with self.j.transaction() as db:
            if int(self.j.meta("epoch", db)) > epoch:
                raise UpdateError("stale_authority")
            db.execute("UPDATE meta SET value=? WHERE key='epoch'", (str(epoch),))
            self.j.event(db, "epoch_handoff_committed", identity)
        self.j.flush_export()
        return epoch

    def freeze(self, operator, parent_job_id, identity):
        parent = self.c.job(operator, parent_job_id)
        self.c.authority.require(operator, "recover", parent["targets"])
        if parent["state"] not in {"unknown", "recovery_required"}:
            raise UpdateError("busy")
        plan, raw = self.c.plan(parent["plan_id"])
        saved = self.j.get("frozen_parent", parent_job_id)
        if saved:
            return saved
        receipts = {}
        for host_id in plan.hosts:
            packet, _ = self._call(
                host_id,
                "freeze_parent",
                identity + "-f-" + host_id,
                parent_job_id=parent_job_id,
                plan=base64.b64encode(raw).decode(),
            )
            receipts[host_id] = packet
        with self.j.transaction() as db:
            self.j.put(
                "frozen_parent",
                parent_job_id,
                {"plan_digest": digest(raw), "receipts": receipts, "child_job_id": None},
                db,
            )
            self.j.event(db, "parent_frozen", parent_job_id)
        self.j.flush_export()
        return self.j.get("frozen_parent", parent_job_id)

    def recover(
        self, operator, parent_job_id, targets, request_key, verify_only=False, approved_digest=None
    ):
        identity = (
            "rc-"
            + digest(
                dumps(
                    {
                        "parent": parent_job_id,
                        "key": request_key,
                        "operator": operator,
                        "targets": targets,
                        "verify": verify_only,
                    }
                )
            ).removeprefix("sha256:")[:24]
        )
        parent = self.c.job(operator, parent_job_id)
        self.c.authority.require(operator, "recover", parent["targets"])
        if set(targets) != set(parent["targets"]):
            raise UpdateError("forbidden", "Recovery must retain the complete parent's scope")
        with exclusive(self.j.directory / "controller.lock"):
            self.gate(identity, True)
            with exclusive(self.j.directory / "coordinator.lock"):
                try:
                    self.advance_epoch(identity, True)
                    frozen = self.freeze(operator, parent_job_id, identity)
                    with self.j.transaction() as db:
                        db.execute("UPDATE meta SET value='active' WHERE key='mode'")
                    action = "verify_recovery" if verify_only else "recover"
                    result = self.c.create_plan(
                        operator, action, targets, request_key, parent_job_id
                    )
                    if approved_digest is None:
                        return result
                    if approved_digest != result["plan_digest"]:
                        raise UpdateError("stale_plan")
                    if result["consumed_job_id"]:
                        child = self.c.job(operator, result["consumed_job_id"])
                        handoff = self.j.get("ownership_handoff", child["job_id"])
                        if not handoff or handoff["state"] == "committed":
                            return child
                    else:
                        grant = self.c.authorize(
                            operator, operator, result["plan_id"], result["plan_digest"]
                        )["authorization_id"]
                        child = (
                            self.c.execute(
                                operator,
                                result["plan_id"],
                                result["plan_digest"],
                                grant,
                                request_key,
                                actions={action},
                            )
                            if verify_only
                            else self._admit_recovery(
                                operator, result, grant, request_key, parent_job_id
                            )
                        )
                    plan, raw = self.c.plan(result["plan_id"])
                    if not verify_only:
                        for host_id in plan.hosts:
                            self._call(
                                host_id,
                                "transfer",
                                identity + "-t-" + host_id,
                                parent_job_id=parent_job_id,
                                child_job_id=child["job_id"],
                                plan=base64.b64encode(raw).decode(),
                            )
                        with self.j.transaction() as db:
                            frozen = self.j.get("frozen_parent", parent_job_id, db)
                            if frozen["child_job_id"] not in {None, child["job_id"]}:
                                raise UpdateError("busy")
                            db.execute(
                                "UPDATE claims SET job_id=? WHERE job_id=?",
                                (child["job_id"], parent_job_id),
                            )
                            self.j.put(
                                "frozen_parent",
                                parent_job_id,
                                {**frozen, "child_job_id": child["job_id"]},
                                db,
                                expected=frozen["_revision"],
                            )
                            self.j.put(
                                "ownership_handoff",
                                child["job_id"],
                                {
                                    "parent_job_id": parent_job_id,
                                    "plan_digest": digest(raw),
                                    "state": "committed",
                                },
                                db,
                            )
                            db.execute(
                                "UPDATE jobs SET state='accepted',revision=revision+1 WHERE id=?",
                                (child["job_id"],),
                            )
                            self.j.event(db, "recovery_ownership_committed", child["job_id"])
                        self.j.flush_export()
                    self.c.run_job(child["job_id"])
                    child = self.c.job(operator, child["job_id"])
                    if child["state"] == "finalizing" and not verify_only:
                        inventory = {}
                        for target in plan.targets:
                            observation = self.c.hosts[self.c.profiles[target].host_id].inspect(
                                target
                            )
                            if (
                                observation.unknown_work
                                or observation.manifest_digest != plan.targets[target]
                                or observation.schemas
                                != self.c.releases.get(plan.targets[target]).schema_targets
                            ):
                                raise UpdateError("outcome_unknown")
                            inventory[target] = observation.model_dump()
                        for host_id in plan.hosts:
                            self._call(
                                host_id,
                                "resolve_parent",
                                identity + "-r-" + host_id,
                                parent_job_id=parent_job_id,
                                child_job_id=child["job_id"],
                            )
                        with self.j.transaction() as db:
                            for target, observed in inventory.items():
                                self.j.put("inventory", target, observed, db)
                            db.execute("DELETE FROM claims WHERE job_id=?", (child["job_id"],))
                            self.j.put(
                                "parent_resolution",
                                parent_job_id,
                                {"child_job_id": child["job_id"], "resolved": True},
                                db,
                            )
                            db.execute(
                                "UPDATE jobs SET state='succeeded',revision=revision+1 WHERE id=?",
                                (child["job_id"],),
                            )
                            self.j.event(db, "parent_recovered", parent_job_id)
                            self.j.event(db, "job_accepted", child["job_id"], "succeeded")
                        self.j.flush_export()
                    return self.c.job(operator, child["job_id"])
                finally:
                    with self.j.transaction() as db:
                        db.execute("UPDATE meta SET value='recovery' WHERE key='mode'")

    def _admit_recovery(self, operator, result, grant, key, parent):
        plan, raw = self.c.plan(result["plan_id"])
        with self.j.transaction() as db:
            old = db.execute("SELECT id FROM jobs WHERE plan_id=?", (plan.id,)).fetchone()
            if old:
                return self.c.job(operator, old[0])
            self.c.authority.check(operator, grant, plan, digest(raw), db)
            frozen = self.j.get("frozen_parent", parent, db)
            if not frozen or frozen["child_job_id"] is not None:
                raise UpdateError("busy")
            child = "job-" + uuid.uuid4().hex
            self.j.put(
                "ownership_handoff",
                child,
                {"parent_job_id": parent, "plan_digest": digest(raw), "state": "intent"},
                db,
            )
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?)",
                (
                    child,
                    plan.id,
                    "recovery_required",
                    1,
                    dumps(
                        {
                            "subject": operator,
                            "authorization_id": grant,
                            "admitted_at": self.c.clock(),
                            "cancel_requested": False,
                            "error": None,
                            "parent_job_id": parent,
                        }
                    ),
                ),
            )
            self.j.event(db, "recovery_ownership_intent", child)
        self.j.flush_export()
        return self.c.job(operator, child)

    def self_update(self, operator, target_manifest, request_key, approved_digest=None):
        self.c.authority.require(operator, "operator", [self.target])
        self.c.authority.require(operator, "recover", [self.target])
        manifest = self.c.releases.get(target_manifest)
        if manifest.application_id != self.c.profiles[self.target].application_id:
            raise UpdateError("forbidden")
        identity = (
            "self-"
            + digest(
                dumps({"operator": operator, "target": target_manifest, "key": request_key})
            ).removeprefix("sha256:")[:24]
        )
        payload = {
            "action": "self_update",
            "target": target_manifest,
            "previous": self.current_manifest,
            "deployment_id": self.target,
            "policy_revision": self.c.policy_revision,
            "epoch": int(self.j.meta("epoch")),
            "expires_at": self.c.clock() + 900,
        }
        with self.j.transaction() as db:
            previous = self.c._request(
                db, operator, "self_plan", request_key, {"target": target_manifest}
            )
            if previous:
                identity = previous
                payload = self.j.get("self_plan", identity, db)["plan"]
            else:
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?)",
                    (
                        operator,
                        "self_plan",
                        request_key,
                        digest(dumps({"target": target_manifest})),
                        identity,
                    ),
                )
                self.j.put("self_plan", identity, {"plan": payload}, db)
        plan_digest = digest(dumps(payload))
        if approved_digest is None:
            return {"plan_id": identity, "plan_digest": plan_digest, **payload}
        if approved_digest != plan_digest or payload["policy_revision"] != self.c.policy_revision:
            raise UpdateError("stale_plan")
        with exclusive(self.j.directory / "controller.lock"):
            old = self.j.get("self_job", identity)
            if old and old["state"] in {"succeeded", "failed_safe", "unknown", "recovery_required"}:
                return old
            if payload["expires_at"] <= self.c.clock() and old is None:
                raise UpdateError("stale_plan")
            with self.j.transaction() as db:
                self.j.put(
                    "self_job",
                    identity,
                    {
                        "state": "preparing",
                        "target": target_manifest,
                        "previous": self.current_manifest,
                    },
                    db,
                )
                self.j.event(db, "self_update_intent", identity)
            self.j.flush_export()
            self.gate(identity, False)
            with exclusive(self.j.directory / "coordinator.lock"):
                epoch = self.advance_epoch(identity, False)
                self._control("self_stage", identity + "-stage", manifest_digest=target_manifest)
                self._control("self_probe", identity + "-probe", manifest_digest=target_manifest)
            try:
                self._control("self_switch", identity + "-switch", manifest_digest=target_manifest)
                health = self._ready(manifest.release, epoch)
                with self.j.transaction() as db:
                    db.execute("UPDATE meta SET value='active' WHERE key='mode'")
                    self.j.put(
                        "self_job",
                        identity,
                        {
                            "state": "succeeded",
                            "target": target_manifest,
                            "previous": self.current_manifest,
                            "epoch": epoch,
                            "readiness": health,
                        },
                        db,
                    )
                    self.j.event(db, "self_update_committed", identity)
                self.j.flush_export()
                return self.j.get("self_job", identity)
            except Exception:
                # Rollback always advances epoch and preserves the current control database.
                self._control("self_stop", identity + "-rollback-stop")
                with exclusive(self.j.directory / "coordinator.lock"):
                    epoch = self.advance_epoch(identity + "-rollback", False)
                    self.c.releases.get(self.current_manifest)
                    self._control(
                        "self_probe",
                        identity + "-rollback-probe",
                        manifest_digest=self.current_manifest,
                    )
                self._control(
                    "self_switch",
                    identity + "-rollback-switch",
                    manifest_digest=self.current_manifest,
                )
                self._ready(self.c.releases.get(self.current_manifest).release, epoch)
                with self.j.transaction() as db:
                    db.execute("UPDATE meta SET value='active' WHERE key='mode'")
                    self.j.put(
                        "self_job",
                        identity,
                        {
                            "state": "failed_safe",
                            "target": target_manifest,
                            "previous": self.current_manifest,
                            "epoch": epoch,
                        },
                        db,
                    )
                    self.j.event(db, "self_update_rolled_back", identity)
                self.j.flush_export()
                return self.j.get("self_job", identity)

    def resume(self, operator, request_key):
        self.c.authority.require(operator, "operator", [self.target])
        self.c.authority.require(operator, "recover", [self.target])
        identity = (
            "resume-"
            + digest(dumps({"operator": operator, "key": request_key})).removeprefix("sha256:")[:24]
        )
        with exclusive(self.j.directory / "controller.lock"):
            self._control("self_switch", identity + "-start", manifest_digest=self.current_manifest)
            self._ready(
                self.c.releases.get(self.current_manifest).release, int(self.j.meta("epoch"))
            )
            with self.j.transaction() as db:
                db.execute("UPDATE meta SET value='active' WHERE key='mode'")
                self.j.event(db, "coordinator_resumed", identity)
            self.j.flush_export()
        return {"mode": "active", "epoch": int(self.j.meta("epoch"))}

    def _ready(self, version, epoch):
        import time

        client = self.readiness.client()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                with client.stream(
                    "GET", self.readiness.url.rstrip("/") + "/health", follow_redirects=False
                ) as response:
                    raw = b""
                    for part in response.iter_bytes():
                        raw += part
                        if len(raw) > 4096:
                            raise UpdateError("outcome_unknown")
                    obj = loads(raw, 4096)
                    if (
                        response.status_code == 200
                        and obj.get("version") == version
                        and obj.get("epoch") == epoch
                        and obj.get("mode") in {"maintenance", "recovery"}
                        and obj.get("journal_version") == 1
                    ):
                        return obj
            except Exception:
                pass
            time.sleep(0.2)
        raise UpdateError(
            "outcome_unknown", "Candidate did not confirm readiness under maintenance"
        )
