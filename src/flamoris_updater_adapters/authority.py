import secrets

from flamoris_update_core.errors import UpdateError


class Authority:
    def __init__(self, journal, clock):
        self.journal, self.clock = journal, clock

    def require(self, subject: str, role: str, targets, db=None) -> dict:
        principal = self.journal.get("principal", subject, db)
        if (
            principal is None
            or not principal.get("active")
            or role not in principal["roles"]
            or not set(targets) <= set(principal["targets"])
        ):
            raise UpdateError("forbidden")
        return principal

    def provision(self, subject: str, roles: list[str], targets: list[str], active: bool = True):
        if not set(roles) <= {
            "read",
            "plan",
            "execute",
            "enroll",
            "cancel",
            "recover_verify",
            "operator",
            "recover",
        }:
            raise UpdateError("invalid_input")
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            self.journal.put(
                "principal", subject, {"roles": roles, "targets": targets, "active": active}, db
            )
            self.journal.event(db, "principal_changed", subject)

    def grant(
        self, operator: str, caller: str, plan, plan_digest: str, deadline: int | None = None
    ) -> str:
        deadline = deadline if deadline is not None else self.clock() + 900
        if not self.clock() < deadline <= min(self.clock() + 3600, plan.expires_at):
            raise UpdateError("invalid_input")
        role = {"enroll": "enroll", "verify_recovery": "recover_verify", "recover": "recover"}.get(
            plan.action, "execute"
        )
        with self.journal.transaction() as db:
            if self.journal.meta("mode", db) != "active":
                raise UpdateError("busy")
            owner = self.require(operator, "operator", plan.targets, db)
            executor = self.require(caller, role, plan.targets, db)
            identity = "grant-" + secrets.token_hex(16)
            self.journal.put(
                "grant",
                identity,
                {
                    "operator": operator,
                    "caller": caller,
                    "operator_revision": owner["_revision"],
                    "caller_revision": executor["_revision"],
                    "plan_id": plan.id,
                    "plan_digest": plan_digest,
                    "action": plan.action,
                    "policy_revision": plan.policy_revision,
                    "deadline": deadline,
                    "revoked": False,
                },
                db,
            )
            self.journal.event(db, "grant_issued", identity)
            return identity

    def check(
        self, caller: str, grant_id: str, plan, plan_digest: str, db=None, admitted: bool = False
    ):
        grant = self.journal.get("grant", grant_id, db)
        role = {"enroll": "enroll", "verify_recovery": "recover_verify", "recover": "recover"}.get(
            plan.action, "execute"
        )
        if (
            grant is None
            or grant["revoked"]
            or grant["caller"] != caller
            or grant["plan_id"] != plan.id
            or grant["plan_digest"] != plan_digest
            or grant["action"] != plan.action
            or grant["policy_revision"] != plan.policy_revision
            or (not admitted and grant["deadline"] <= self.clock())
        ):
            raise UpdateError("forbidden")
        owner = self.require(grant["operator"], "operator", plan.targets, db)
        executor = self.require(caller, role, plan.targets, db)
        if (
            grant["operator_revision"] != owner["_revision"]
            or grant["caller_revision"] != executor["_revision"]
        ):
            raise UpdateError("policy_changed")

    def revoke(self, operator: str, grant_id: str):
        with self.journal.transaction() as db:
            grant = self.journal.get("grant", grant_id, db)
            if grant is None:
                raise UpdateError("forbidden")
            with self.journal.connection() as reader:
                row = reader.execute(
                    "SELECT payload FROM plans WHERE id=?", (grant["plan_id"],)
                ).fetchone()
            from flamoris_update_core.models import Plan
            from flamoris_update_core.wire import decode

            plan = decode(Plan, row[0])
            self.require(operator, "operator", plan.targets, db)
            self.journal.put("grant", grant_id, {**grant, "revoked": True}, db)
            self.journal.event(db, "grant_revoked", grant_id)
