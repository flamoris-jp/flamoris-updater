import base64
import sqlite3
import threading
import uuid

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import Plan
from flamoris_update_core.planner import Planner
from flamoris_update_core.wire import decode, digest, dumps, loads
from flamoris_updater_adapters.executor import receipt
from flamoris_updater_adapters.journal import exclusive
from flamoris_updater_adapters.signing import open_packet

from .policy import verify_managed_release

TERMINAL = {"succeeded", "failed_safe", "cancelled_safe", "recovery_required", "unknown"}


class Coordinator:
    def __init__(
        self,
        domain,
        journal,
        profiles,
        resources,
        releases,
        hosts,
        authority,
        signer,
        receipt_keys,
        clock,
        policy_revision=1,
    ):
        self.domain, self.journal, self.profiles = domain, journal, profiles
        self.planner = Planner(profiles, resources)
        self.releases, self.hosts, self.authority = releases, hosts, authority
        self.signer, self.receipt_keys, self.clock = signer, receipt_keys, clock
        self.policy_revision = policy_revision
        self.guard = lambda: None
        self.wakeup, self.stopping = threading.Event(), threading.Event()

    def _request(self, db, subject, action, key, payload):
        if not isinstance(key, str) or not 1 <= len(key) <= 128:
            raise UpdateError("invalid_input")
        row = db.execute(
            "SELECT digest,result_id FROM requests WHERE subject=? AND action=? AND key=?",
            (subject, action, key),
        ).fetchone()
        if row and row[0] != digest(dumps(payload)):
            raise UpdateError("idempotency_conflict")
        return row[1] if row else None

    def get_plan(self, subject, identity):
        plan, raw = self.plan(identity)
        self.authority.require(subject, "read", plan.targets)
        with self.journal.connection() as db:
            consumed = db.execute("SELECT id FROM jobs WHERE plan_id=?", (identity,)).fetchone()
        return {
            "plan_id": plan.id,
            "plan_digest": digest(raw),
            "action": plan.action,
            "targets": plan.targets,
            "resources": plan.resources,
            "hosts": plan.hosts,
            "expires_at": plan.expires_at,
            "steps": [
                {
                    "id": s.id,
                    "deployment_id": s.deployment_id,
                    "phase": s.phase,
                    "operation": s.operation,
                }
                for s in plan.steps
            ],
            "parent_job_id": plan.parent_job_id,
            "consumed_job_id": consumed[0] if consumed else None,
        }

    def plan(self, identity):
        with self.journal.connection() as db:
            row = db.execute("SELECT digest,payload FROM plans WHERE id=?", (identity,)).fetchone()
            if row is None:
                raise UpdateError("forbidden")
            if digest(row[1]) != row[0]:
                raise UpdateError("journal_corrupt")
            return decode(Plan, row[1]), row[1]

    def create_plan(self, subject, action, targets, request_key, parent_job_id=None):
        if action not in {"update", "install", "verify_recovery", "recover"}:
            raise UpdateError("invalid_input")
        self.guard()
        payload = {"action": action, "targets": targets, "parent_job_id": parent_job_id}
        self.authority.require(subject, "plan", targets)
        with self.journal.transaction() as db:
            previous = self._request(db, subject, "plan", request_key, payload)
            if previous:
                return self.get_plan(subject, previous)
        if self.journal.meta("mode") != "active":
            raise UpdateError("busy")
        if parent_job_id is not None:
            parent = self.job(subject, parent_job_id)
            if parent["state"] not in {"unknown", "recovery_required"}:
                raise UpdateError("busy")
        observed, current = {}, {}
        for identity in sorted(self.planner.inspected(targets, action)):
            profile = self.profiles[identity]
            obs = self.hosts[profile.host_id].inspect(identity)
            observed[identity] = obs
            if obs.manifest_digest:
                current[identity] = self.releases.get(obs.manifest_digest, eligible=False)
        manifests = dict(current)
        for identity, release_id in targets.items():
            manifests[identity] = self.releases.get(release_id)
        plan = self.planner.build(
            action,
            targets,
            manifests,
            observed,
            current,
            self.clock(),
            self.policy_revision,
            int(self.journal.meta("epoch")),
            parent_job_id,
        )
        from flamoris_update_core.inventory import fingerprint

        dependency_observations = {
            i: fingerprint(o) for i, o in observed.items() if i not in plan.targets
        }
        plan = plan.model_copy(
            update={
                "provider_observations": dependency_observations,
                "hosts": sorted(
                    set(plan.hosts) | {self.profiles[i].host_id for i in dependency_observations}
                ),
            }
        )
        plan = plan.model_copy(
            update={
                "catalog_sequences": {
                    manifests[i].application_id: self.releases._catalog(
                        manifests[i].application_id
                    )["sequence"]
                    for i in plan.targets
                }
            }
        )
        if action == "recover":
            if not self.journal.get("frozen_parent", parent_job_id):
                raise UpdateError("recovery_required")
            parent_plan, parent_raw = self.plan(parent["plan_id"])
            if plan.targets != parent_plan.previous_targets:
                raise UpdateError(
                    "forbidden", "Recovery requires the recorded previous executables"
                )
        self.authority.require(subject, "plan", plan.targets)
        for identity in plan.targets:
            verify_managed_release(self.profiles[identity], observed[identity], action)
            self.releases.get(plan.targets[identity])
        raw = dumps(plan)
        if len(raw) > 512 * 1024:
            raise UpdateError("invalid_input", "Plan exceeds admission budget")
        with self.journal.transaction() as db:
            previous = self._request(db, subject, "plan", request_key, payload)
            if previous:
                return self.get_plan(subject, previous)
            db.execute("INSERT INTO plans VALUES(?,?,?)", (plan.id, digest(raw), raw))
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?)",
                (subject, "plan", request_key, digest(dumps(payload)), plan.id),
            )
            self.journal.event(db, "plan_created", plan.id)
        return self.get_plan(subject, plan.id)

    def authorize(self, operator, caller, plan_id, plan_digest):
        self.guard()
        plan, raw = self.plan(plan_id)
        if digest(raw) != plan_digest:
            raise UpdateError("stale_plan")
        return {"authorization_id": self.authority.grant(operator, caller, plan, plan_digest)}

    def execute(
        self,
        subject,
        plan_id,
        plan_digest,
        authorization_id,
        request_key,
        actions=frozenset({"update", "install"}),
        protected=False,
    ):
        self.guard()
        plan, raw = self.plan(plan_id)
        if plan.action not in actions or (plan.action == "recover" and not protected):
            raise UpdateError("forbidden")
        self.authority.require(subject, "read", plan.targets)
        payload = {
            "plan_id": plan_id,
            "plan_digest": plan_digest,
            "authorization_id": authorization_id,
        }
        with self.journal.transaction() as db:
            previous = self._request(db, subject, "execute", request_key, payload)
            if previous:
                return self.job(subject, previous)
            consumed = db.execute("SELECT id FROM jobs WHERE plan_id=?", (plan_id,)).fetchone()
            if consumed:
                return self.job(subject, consumed[0])
            self.authority.check(subject, authorization_id, plan, plan_digest, db)
            if (
                digest(raw) != plan_digest
                or plan.expires_at <= self.clock()
                or plan.policy_revision != self.policy_revision
                or plan.coordinator_epoch != int(self.journal.meta("epoch", db))
                or self.journal.meta("mode", db) != "active"
            ):
                raise UpdateError("stale_plan")
            identity = "job-" + uuid.uuid4().hex
            if plan.action == "recover":
                raise UpdateError(
                    "protected_target", "Use the independent recovery ownership protocol"
                )
            if plan.action != "verify_recovery":
                try:
                    for kind, resource_id in [("host", h) for h in plan.hosts] + [
                        ("resource", r) for r in plan.resources
                    ]:
                        db.execute(
                            "INSERT INTO claims VALUES(?,?,?)", (kind, resource_id, identity)
                        )
                except sqlite3.IntegrityError:
                    raise UpdateError("busy") from None
            info = {
                "subject": subject,
                "authorization_id": authorization_id,
                "admitted_at": self.clock(),
                "cancel_requested": False,
                "error": None,
                "parent_job_id": plan.parent_job_id,
            }
            db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?)",
                (identity, plan.id, "accepted", 1, dumps(info)),
            )
            db.execute(
                "INSERT INTO requests VALUES(?,?,?,?,?)",
                (subject, "execute", request_key, digest(dumps(payload)), identity),
            )
            self.journal.event(db, "job_admitted", identity)
        self.journal.flush_export()
        self.wakeup.set()
        return self.job(subject, identity)

    def job(self, subject, identity):
        with self.journal.connection() as db:
            row = db.execute(
                "SELECT plan_id,state,revision,payload FROM jobs WHERE id=?", (identity,)
            ).fetchone()
        if row is None:
            raise UpdateError("forbidden")
        plan, _ = self.plan(row["plan_id"])
        self.authority.require(subject, "read", plan.targets)
        info = loads(row["payload"])
        resolution = self.journal.get("parent_resolution", identity)
        return {
            "resolution_job_id": resolution["child_job_id"] if resolution else None,
            "job_id": identity,
            "plan_id": plan.id,
            "state": row["state"],
            "revision": row["revision"],
            "targets": plan.targets,
            "cancel_requested": info["cancel_requested"],
            "error": info["error"],
            "parent_job_id": info["parent_job_id"],
            "blocked_resources": plan.resources
            if not resolution and row["state"] not in {"succeeded", "failed_safe", "cancelled_safe"}
            else [],
        }

    def cancel(self, subject, identity, request_key):
        self.job(subject, identity)
        with self.journal.transaction() as db:
            row = db.execute(
                "SELECT plan_id,state,payload FROM jobs WHERE id=?", (identity,)
            ).fetchone()
            plan, _ = self.plan(row["plan_id"])
            if plan.action == "recover":
                raise UpdateError("protected_target")
            self.authority.require(subject, "cancel", plan.targets, db)
            payload = {"job_id": identity}
            previous = self._request(db, subject, "cancel", request_key, payload)
            if not previous:
                info = loads(row["payload"])
                info["cancel_requested"] = True
                db.execute(
                    "UPDATE jobs SET payload=?,revision=revision+1 WHERE id=?",
                    (dumps(info), identity),
                )
                db.execute(
                    "INSERT INTO requests VALUES(?,?,?,?,?)",
                    (subject, "cancel", request_key, digest(dumps(payload)), identity),
                )
                self.journal.event(db, "cancel_requested", identity)
        self.wakeup.set()
        return self.job(subject, identity)

    def _state(self, identity, state, error=None):
        with self.journal.transaction() as db:
            row = db.execute("SELECT payload FROM jobs WHERE id=?", (identity,)).fetchone()
            info = loads(row[0])
            info["error"] = error
            db.execute(
                "UPDATE jobs SET state=?,payload=?,revision=revision+1 WHERE id=?",
                (state, dumps(info), identity),
            )
            self.journal.event(db, "job_state", identity, state)
        self.journal.flush_export()

    def run_job(self, identity):
        with self.journal.connection() as db:
            row = db.execute(
                "SELECT plan_id,state,payload FROM jobs WHERE id=?", (identity,)
            ).fetchone()
        if row is None or row["state"] in TERMINAL:
            return
        plan, raw = self.plan(row["plan_id"])
        info = loads(row["payload"])
        try:
            for step in plan.steps:
                self.guard()
                known = self.journal.get("receipt", identity + "." + step.id)
                if known:
                    continue
                with self.journal.connection() as db:
                    info = loads(
                        db.execute("SELECT payload FROM jobs WHERE id=?", (identity,)).fetchone()[0]
                    )
                if info["cancel_requested"]:
                    self._cancel_job(identity, plan)
                    return
                self.authority.check(
                    info["subject"], info["authorization_id"], plan, digest(raw), admitted=True
                )
                if (
                    self.policy_revision != plan.policy_revision
                    or plan.coordinator_epoch != int(self.journal.meta("epoch"))
                    or self.journal.meta("mode") != "active"
                ):
                    raise UpdateError("policy_changed")
                from flamoris_update_core.inventory import fingerprint

                for provider_id, expected in plan.provider_observations.items():
                    if (
                        fingerprint(
                            self.hosts[self.profiles[provider_id].host_id].inspect(provider_id)
                        )
                        != expected
                    ):
                        raise UpdateError("stale_plan", "Bound provider changed")
                for manifest_digest in plan.targets.values():
                    trusted = self.releases.get(manifest_digest)
                    if self.releases._catalog(trusted.application_id)[
                        "sequence"
                    ] < plan.catalog_sequences.get(trusted.application_id, 1):
                        raise UpdateError("catalog_replay")
                predecessors = {}
                for previous in step.predecessors:
                    saved = self.journal.get("receipt", identity + "." + previous)
                    if saved is None:
                        raise UpdateError("outcome_unknown")
                    predecessors[previous] = saved["packet"]
                ticket = self.signer.packet(
                    {
                        "ticket_version": 1,
                        "domain": self.domain,
                        "host_id": step.host_id,
                        "epoch": plan.coordinator_epoch,
                        "admitted_at": info["admitted_at"],
                        "job_id": identity,
                        "plan": base64.b64encode(raw).decode(),
                        "step_id": step.id,
                        "predecessors": predecessors,
                    }
                )
                if len(dumps(ticket)) > 1024 * 1024:
                    raise UpdateError("invalid_input", "Step ticket exceeds transport budget")
                self._state(identity, step.phase)
                result = self.hosts[step.host_id].run(ticket)
                if result["outcome"] not in {"verified", "applied_verified"} or not result.get(
                    "receipt"
                ):
                    raise UpdateError("outcome_unknown")
                receipt(
                    result["receipt"], self.receipt_keys, self.domain, identity, digest(raw), step
                )
                with self.journal.transaction() as db:
                    self.journal.put(
                        "receipt", identity + "." + step.id, {"packet": result["receipt"]}, db
                    )
                    self.journal.event(db, "step_confirmed", identity + "." + step.id)
            # Final inventory commit occurs only after every local release was acknowledged.
            inventory = {}
            if plan.action != "verify_recovery":
                for target in plan.targets:
                    observed = self.hosts[self.profiles[target].host_id].inspect(target)
                    if (
                        observed.manifest_digest != plan.targets[target]
                        or observed.unknown_work
                        or observed.schemas
                        != self.releases.get(plan.targets[target]).schema_targets
                    ):
                        raise UpdateError("outcome_unknown")
                    inventory[target] = observed.model_dump()
            if plan.action == "recover":
                self._state(identity, "finalizing")
                return  # Protected controller performs linked acceptance atomically after host resolution.
            with self.journal.transaction() as db:
                for target, observation in inventory.items():
                    self.journal.put("inventory", target, observation, db)
                db.execute("DELETE FROM claims WHERE job_id=?", (identity,))
                db.execute(
                    "UPDATE jobs SET state='succeeded',revision=revision+1 WHERE id=?", (identity,)
                )
                self.journal.event(db, "job_accepted", identity, "succeeded")
            self.journal.flush_export()
        except Exception as error:
            code = error.code if isinstance(error, UpdateError) else "outcome_unknown"
            self._state(
                identity, "unknown" if code == "outcome_unknown" else "recovery_required", code
            )

    def _cancel_job(self, identity, plan):
        prepared = [s for s in plan.steps if self.journal.get("receipt", identity + "." + s.id)]
        if any(s.operation not in {"prepare", "begin"} for s in prepared):
            self._state(identity, "recovery_required", "cancel_requires_recovery")
            return
        if prepared:
            for host_id in sorted({s.host_id for s in prepared}):
                packet = self.signer.packet(
                    {
                        "command": "abort_preparation",
                        "domain": self.domain,
                        "host_id": host_id,
                        "epoch": plan.coordinator_epoch,
                        "job_id": identity,
                    }
                )
                response = self.hosts[host_id].abort(packet)
                if response.get("signature", {}).get("key_id") != host_id:
                    raise UpdateError("outcome_unknown")
                evidence = open_packet(response, self.receipt_keys, self.domain, "receipt")
                if evidence != {
                    "command": "preparation_aborted",
                    "job_id": identity,
                    "host_id": host_id,
                }:
                    raise UpdateError("outcome_unknown")
        with self.journal.transaction() as db:
            db.execute("DELETE FROM claims WHERE job_id=?", (identity,))
            db.execute(
                "UPDATE jobs SET state='cancelled_safe',revision=revision+1 WHERE id=?", (identity,)
            )
            self.journal.event(db, "job_cancelled", identity, "cancelled_safe")
        self.journal.flush_export()

    def history(self, subject, cursor="", limit=50):
        if not 1 <= limit <= 100:
            raise UpdateError("invalid_input")
        self.authority.require(subject, "read", [])
        with self.journal.connection() as db:
            rows = db.execute(
                "SELECT id FROM jobs WHERE id>? ORDER BY id LIMIT ?", (cursor, limit)
            ).fetchall()
        results = []
        for row in rows:
            try:
                results.append(self.job(subject, row[0]))
            except UpdateError:
                pass
        return {"items": results, "next_cursor": rows[-1][0] if len(rows) == limit else None}

    def inventory(self, subject, cursor="", limit=50):
        principal = self.authority.require(subject, "read", [])
        rows = self.journal.list("inventory", cursor, limit)
        items = [
            {
                "deployment_id": x["id"],
                "application_id": x["application_id"],
                "release": x["release"],
                "manifest_digest": x["manifest_digest"],
                "observed_at": x.get("observed_at", 0),
                "stale": x.get("observed_at", 0) < self.clock() - 300,
            }
            for x in rows
            if x["id"] in principal["targets"]
        ]
        return {"items": items, "next_cursor": rows[-1]["id"] if len(rows) == limit else None}

    def worker(self, own_lock=True):
        from contextlib import nullcontext

        with exclusive(self.journal.directory / "coordinator.lock") if own_lock else nullcontext():
            while self.journal.meta("mode") != "active" and not self.stopping.is_set():
                self.stopping.wait(0.25)
            if self.journal.meta("mode") != "active":
                return
            with self.journal.transaction() as db:
                interrupted = db.execute(
                    "SELECT id FROM jobs WHERE state NOT IN ('accepted','succeeded','failed_safe','cancelled_safe','recovery_required','unknown')"
                ).fetchall()
                for row in interrupted:
                    db.execute(
                        "UPDATE jobs SET state='unknown',revision=revision+1 WHERE id=?", (row[0],)
                    )
                    self.journal.event(db, "job_interrupted", row[0], "unknown")
            self.journal.flush_export()
            while not self.stopping.is_set():
                if self.journal.meta("mode") != "active":
                    self.stopping.wait(0.25)
                    continue
                with self.journal.connection() as db:
                    jobs = [
                        r[0]
                        for r in db.execute(
                            "SELECT id FROM jobs WHERE state='accepted' ORDER BY id"
                        )
                    ]
                for identity in jobs:
                    if self.stopping.is_set():
                        break
                    self.run_job(identity)
                self.wakeup.wait(0.25)
                self.wakeup.clear()
