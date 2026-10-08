"""Independent, application-owned entry transition before coordinator enrollment."""

import argparse
import uuid
from pathlib import Path

from pydantic import Field

from flamoris_update_core.contracts import OwnerRequest, verified
from flamoris_update_core.errors import UpdateError
from flamoris_update_core.inventory import fingerprint
from flamoris_update_core.models import ID, Digest, Manifest, Model
from flamoris_update_core.signing import verify
from flamoris_update_core.wire import decode, digest, dumps

from .config import HelperConfig, load, protected_read
from .journal import durable_write, exclusive
from .runtime import executor, pinned_keys


class EntryConfiguration(Model):
    helper_config_file: str
    deployment_id: ID
    manifest_file: str
    baseline_tag: str
    baseline_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_source_state_digest: Digest


class EntryPlan(Model):
    entry_plan_version: int = 1
    id: ID
    deployment_id: ID
    application_id: ID
    configuration_digest: Digest
    manifest_digest: Digest
    artifact_digest: Digest
    observation_digest: Digest
    source_state_digest: Digest
    baseline_tag: str
    baseline_revision: str
    target_release: str
    schemas: dict[str, str]
    created_at: int
    expires_at: int


class EntryTransition:
    def __init__(self, config, host, profile, target, manifest_digest, configuration_digest):
        self.config, self.host, self.profile, self.target = config, host, profile, target
        self.manifest_digest, self.configuration_digest = manifest_digest, configuration_digest
        self.owner = host.backend.owners[profile.id]
        self.driver = host.backend.drivers[profile.id]

    def plan(self):
        p, target = self.profile, self.target
        gpu = p.application_id == "flamoris-gpu-node-manager"
        if (
            p.role != "application"
            or target.release != ("1.2.0" if gpu else "1.0.0")
            or self.config.baseline_tag != ("v1.1" if gpu else "v0.1")
            or target.migrations
            or target.initialization.supported
        ):
            raise UpdateError("unsupported_migration")
        observation = self.host.inspect(p.id)
        if (
            observation.active_work
            or observation.unknown_work
            or observation.entry_evidence is not None
            or observation.schemas != target.schema_targets
        ):
            raise UpdateError("entry_required")
        source = digest(dumps(self.driver.source_state()))
        if source != self.config.expected_source_state_digest:
            raise UpdateError("stale_plan")
        now = self.host.clock()
        return EntryPlan(
            id="entry-" + uuid.uuid4().hex,
            deployment_id=p.id,
            application_id=p.application_id,
            configuration_digest=self.configuration_digest,
            manifest_digest=self.manifest_digest,
            artifact_digest=target.artifact.digest,
            observation_digest=fingerprint(observation),
            source_state_digest=source,
            baseline_tag=self.config.baseline_tag,
            baseline_revision=self.config.baseline_revision,
            target_release=target.release,
            schemas=target.schema_targets,
            created_at=now,
            expires_at=now + 900,
        )

    def apply(self, plan, confirmation):
        raw, journal = dumps(plan), self.host.journal
        plan_digest = digest(raw)
        if confirmation != plan_digest:
            raise UpdateError("confirmation_required")
        with exclusive(journal.directory / "entry.lock"):
            if journal.get("entry_job", plan.id):
                # Even a confirmed success is inspected via status. No replay
                # of a partially completed host/owner operation is implicit.
                raise UpdateError("recovery_required")
            current = self.plan()
            excluded = {"id", "created_at", "expires_at"}
            if (
                plan.entry_plan_version != 1
                or self.host.clock() > plan.expires_at
                or self.host.clock() < plan.created_at
                or current.model_dump(exclude=excluded) != plan.model_dump(exclude=excluded)
            ):
                raise UpdateError("stale_plan")
            with journal.transaction() as db:
                self._reserve(plan, plan_digest, db)
                journal.put(
                    "entry_job",
                    plan.id,
                    {
                        "plan_digest": plan_digest,
                        "plan": plan.model_dump(),
                        "phase": "accepted",
                        "step": None,
                        "result": None,
                    },
                    db,
                )
                journal.event(db, "entry_accepted", plan.id)
            journal.flush_export()
            epochs = {}
            try:
                for operation in [
                    "prepare",
                    "begin",
                    "close_admission",
                    "drain",
                    "stop",
                    "snapshot",
                    "restore_verify",
                    "activate",
                    "validate",
                    "reopen_admission",
                    "release",
                ]:
                    with journal.transaction() as db:
                        job = journal.get("entry_job", plan.id, db)
                        journal.put(
                            "entry_job", plan.id, {**job, "phase": "intent", "step": operation}, db
                        )
                        journal.event(db, "entry_intent", plan.id, operation)
                    journal.flush_export()
                    request = OwnerRequest(
                        operation=operation,
                        application_id=plan.application_id,
                        deployment_id=plan.deployment_id,
                        artifact_digest=plan.artifact_digest,
                        operation_id=plan.id + "." + operation,
                        job_id=plan.id,
                        plan_digest=plan_digest,
                        resource_ids=sorted(self.profile.resources.values()),
                        expected_schemas=plan.schemas,
                        maintenance_epochs=epochs,
                        predecessor_receipts=[],
                        arguments={
                            "standalone_transition": True,
                            "read_only": False,
                            "manifest_digest": plan.manifest_digest,
                        },
                    )
                    if operation == "prepare":
                        self.driver.prepare(self.target)
                    result = self.host.backend.perform(self.profile, self.target, request)
                    verified(request, result)
                    if operation == "close_admission":
                        if set(result.maintenance_epochs) != set(self.profile.resources.values()):
                            raise UpdateError("outcome_unknown")
                        epochs = result.maintenance_epochs
                    with journal.transaction() as db:
                        journal.put(
                            "entry_receipt",
                            plan.id + "." + operation,
                            {"request": request.model_dump(), "result": result.model_dump()},
                            db,
                        )
                        journal.event(db, "entry_result", plan.id, operation)
                    journal.flush_export()
                observation = self.host.inspect(self.profile.id)
                if (
                    observation.manifest_digest != plan.manifest_digest
                    or observation.release != plan.target_release
                    or observation.entry_evidence != "standalone_transition"
                ):
                    raise UpdateError("outcome_unknown")
                with journal.transaction() as db:
                    job = journal.get("entry_job", plan.id, db)
                    journal.put(
                        "entry_job",
                        plan.id,
                        {**job, "phase": "succeeded", "result": observation.model_dump()},
                        db,
                    )
                    db.execute("DELETE FROM claims WHERE job_id=?", (plan.id,))
                    journal.event(db, "entry_succeeded", plan.id)
                journal.flush_export()
                return {"job_id": plan.id, "phase": "succeeded", "enrollment_required": True}
            except BaseException:
                with journal.transaction() as db:
                    job = journal.get("entry_job", plan.id, db)
                    journal.put("entry_job", plan.id, {**job, "phase": "recovery_required"}, db)
                    journal.event(db, "entry_unknown", plan.id)
                journal.flush_export()
                raise

    def _reserve(self, plan, plan_digest, db):
        identities = [
            ("deployment", self.profile.id),
            *(("resource", r) for r in self.profile.resources.values()),
        ]
        for kind, identity in identities:
            if db.execute(
                "SELECT 1 FROM claims WHERE kind=? AND id=?", (kind, identity)
            ).fetchone():
                raise UpdateError("busy")
            db.execute("INSERT INTO claims VALUES(?,?,?)", (kind, identity, plan.id))


def configured(path):
    cfg = load(EntryConfiguration, path, root_only=True)
    helper_raw = protected_read(cfg.helper_config_file, root_only=True)
    helper = decode(HelperConfig, helper_raw)
    _, host = executor(cfg.helper_config_file)
    profile = host.profiles.get(cfg.deployment_id)
    if profile is None:
        raise UpdateError("invalid_profile")
    raw = protected_read(cfg.manifest_file)
    target = decode(Manifest, raw)
    verify(
        raw,
        protected_read(cfg.manifest_file + ".sig"),
        pinned_keys(helper.release_keys),
        profile.application_id,
        "release",
    )
    revision = digest(dumps({"entry": cfg.model_dump(), "helper": digest(helper_raw)}))
    return EntryTransition(
        cfg,
        host,
        profile,
        target.select(profile.platform, profile.artifact_kind),
        digest(raw),
        revision,
    )


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Standalone application entry transition; no coordinator enrollment needed"
    )
    parser.add_argument("--config", required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("source")
    plan = commands.add_parser("plan")
    plan.add_argument("--output", required=True)
    apply = commands.add_parser("apply")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--confirm", required=True, help="Exact SHA256 of the reviewed plan")
    status = commands.add_parser("status")
    status.add_argument("--job", required=True)
    args = parser.parse_args(argv)
    try:
        transition = configured(args.config)
        if args.command == "source":
            print(
                dumps(
                    {"source_state_digest": digest(dumps(transition.driver.source_state()))}
                ).decode()
            )
        elif args.command == "plan":
            output = Path(args.output)
            if not output.is_absolute() or output.exists() or output.is_symlink():
                raise UpdateError("unsafe_storage")
            result = transition.plan()
            durable_write(output, dumps(result))
            print(
                dumps(
                    {
                        "plan_id": result.id,
                        "plan_digest": digest(dumps(result)),
                        "expires_at": result.expires_at,
                    }
                ).decode()
            )
        elif args.command == "apply":
            result = transition.apply(
                decode(EntryPlan, protected_read(args.plan, private=True)), args.confirm
            )
            print(dumps(result).decode())
        else:
            job = transition.host.journal.get("entry_job", args.job)
            if job is None:
                raise UpdateError("invalid_input")
            print(dumps({"job_id": args.job, "phase": job["phase"], "step": job["step"]}).decode())
    except (UpdateError, OSError, ValueError) as error:
        print(
            dumps(
                {
                    "error": error.code if isinstance(error, UpdateError) else "outcome_unknown",
                    "automatic_replay": False,
                }
            ).decode()
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
