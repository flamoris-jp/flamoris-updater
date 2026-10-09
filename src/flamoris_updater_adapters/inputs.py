from typing import Literal

from pydantic import Field

from flamoris_update_core.models import ID, Digest, Model

from .managed import MANAGED_TOOLS


class Page(Model):
    cursor: str = Field(default="", max_length=128)
    limit: int = Field(default=50, ge=1, le=100)


class TargetPage(Page):
    targets: list[ID] | None = None


class Application(Model):
    application_id: ID
    channel: ID = "stable"


class NotesRequest(Model):
    application_id: ID
    from_release: str
    to_release: str
    cursor: str = Field(default="", max_length=128)
    limit: int = Field(default=20, ge=1, le=100)


class PlanRequest(Model):
    targets: dict[ID, Digest] = Field(min_length=1, max_length=128)
    request_key: str = Field(min_length=1, max_length=128)


class PlanID(Model):
    plan_id: ID


class ExecuteRequest(Model):
    plan_id: ID
    plan_digest: Digest
    authorization_id: ID
    request_key: str = Field(min_length=1, max_length=128)


class GrantRequest(Model):
    plan_id: ID
    plan_digest: Digest
    caller_id: ID


class JobID(Model):
    job_id: ID


class CancelRequest(JobID):
    request_key: str = Field(min_length=1, max_length=128)


class RecoveryPlanRequest(PlanRequest):
    parent_job_id: ID
    action: Literal["verify_recovery", "recover"]


class RecoveryVerifyRequest(ExecuteRequest):
    parent_job_id: ID


TOOLS = {
    "updater_inventory_list": (TargetPage, "Inventory and observation freshness", "read"),
    "updater_releases_list": (Application, "Trusted application release candidates", "read"),
    "updater_release_notes_get": (NotesRequest, "Ordered bounded release notes", "read"),
    "updater_update_plan": (PlanRequest, "Immutable application update plan", "plan"),
    "updater_install_plan": (PlanRequest, "Explicit empty-state initialization plan", "plan"),
    "updater_plan_get": (PlanID, "Scoped exact-plan summary", "read"),
    "updater_update_execute": (
        ExecuteRequest,
        "Admit an operator-authorized durable Job",
        "execute",
    ),
    "updater_job_get": (JobID, "Durable Job status and blockers", "read"),
    "updater_job_cancel": (CancelRequest, "Request cancellation at a safe boundary", "cancel"),
    "updater_history_list": (Page, "Scoped update and recovery history", "read"),
    "updater_recovery_plan": (
        RecoveryPlanRequest,
        "Typed verification or protected recovery plan",
        "plan",
    ),
    "updater_recovery_verify": (
        RecoveryVerifyRequest,
        "Evidence-only recovery verification child",
        "verify",
    ),
}
TOOLS.update(MANAGED_TOOLS)


class Facade:
    def __init__(self, coordinator):
        self.coordinator = coordinator

    def application(self, subject, application_id):
        principal = self.coordinator.authority.require(subject, "read", [])
        if not any(
            p.application_id == application_id and p.id in principal["targets"]
            for p in self.coordinator.profiles.values()
        ):
            from flamoris_update_core.errors import UpdateError

            raise UpdateError("forbidden")

    def invoke(self, subject, name, payload):
        from flamoris_update_core.errors import UpdateError

        if name not in TOOLS:
            raise UpdateError("invalid_input")
        model = TOOLS[name][0]
        try:
            args = model.model_validate(payload)
        except Exception:
            raise UpdateError("invalid_input", "Arguments do not match the tool contract") from None
        c = self.coordinator
        if hasattr(c, "managed_invoke"):
            return c.managed_invoke(subject, name, payload)
        if name in MANAGED_TOOLS:
            raise UpdateError(
                "invalid_input", "Managed installation requires the bootstrap service"
            )
        if name == "updater_inventory_list":
            result = c.inventory(subject, args.cursor, args.limit)
            if args.targets is not None:
                c.authority.require(subject, "read", args.targets)
                result["items"] = [x for x in result["items"] if x["deployment_id"] in args.targets]
            return result
        if name == "updater_releases_list":
            self.application(subject, args.application_id)
            return {"items": c.releases.candidates(args.application_id, args.channel)}
        if name == "updater_release_notes_get":
            self.application(subject, args.application_id)
            return c.releases.notes(
                args.application_id, args.from_release, args.to_release, args.cursor, args.limit
            )
        if name in {"updater_update_plan", "updater_install_plan"}:
            action = {
                "updater_update_plan": "update",
                "updater_install_plan": "install",
            }[name]
            return c.create_plan(subject, action, args.targets, args.request_key)
        if name == "updater_plan_get":
            return c.get_plan(subject, args.plan_id)
        if name in {"updater_update_execute", "updater_recovery_verify"}:
            allowed = {
                "updater_update_execute": {"update", "install"},
                "updater_recovery_verify": {"verify_recovery"},
            }[name]
            if name == "updater_recovery_verify":
                plan, _ = c.plan(args.plan_id)
                if plan.parent_job_id != args.parent_job_id:
                    raise UpdateError("forbidden")
            return c.execute(
                subject,
                args.plan_id,
                args.plan_digest,
                args.authorization_id,
                args.request_key,
                actions=allowed,
            )
        if name == "updater_job_get":
            return c.job(subject, args.job_id)
        if name == "updater_job_cancel":
            return c.cancel(subject, args.job_id, args.request_key)
        if name == "updater_history_list":
            return c.history(subject, args.cursor, args.limit)
        if name == "updater_recovery_plan":
            return c.create_plan(
                subject, args.action, args.targets, args.request_key, args.parent_job_id
            )
        raise UpdateError("invalid_input")
