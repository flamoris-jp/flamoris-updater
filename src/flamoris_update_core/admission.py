"""Process-independent admission and durable uncertainty for application owners.

All accepted work has a durable token. A crashed or cancelled writer is never
made idle by elapsed time, a PID check, or a service restart.
"""

import contextlib
import functools
import os
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ParamSpec, TypeVar, cast

from .errors import UpdateError

P = ParamSpec("P")
R = TypeVar("R")
CURRENT: ContextVar[str | None] = ContextVar("update_admission", default=None)
UNCERTAIN = {
    "provider_timeout",
    "provider_unavailable",
    "internal_error",
    "cleanup_failed",
    "startup_failed",
    "submission_unknown",
    "unknown",
    "outcome_unknown",
}


@dataclass
class Ticket:
    identity: str
    known: bool = True


class Admission:
    def __init__(self, directory: Path):
        from .journal import Journal

        self.journal = Journal(directory)

    def state(self):
        with self.journal.connection() as db:
            gate = self.journal.get("admission", "gate", db)
            rows = db.execute("SELECT payload FROM records WHERE kind='accepted_work'").fetchall()
        from .wire import loads

        work = [loads(row[0]) for row in rows]
        return {
            "closed": gate is None or gate["closed"],
            "epoch": 0 if gate is None else gate["epoch"],
            "job_id": None if gate is None else gate["job_id"],
            "active_work": bool(work),
            "unknown_work": any(item["outcome"] == "unknown" for item in work),
            "work_ids": [item["id"] for item in work],
        }

    def close(self, job_id: str):
        with self.journal.transaction() as db:
            old = self.journal.get("admission", "gate", db)
            if old and old["closed"] and old["job_id"] != job_id:
                raise UpdateError("maintenance_conflict")
            epoch = (old or {}).get("epoch", 0)
            if not old or not old["closed"]:
                epoch += 1
            self.journal.put(
                "admission", "gate", {"closed": True, "epoch": epoch, "job_id": job_id}, db
            )
        self.journal.flush_export()
        return epoch

    def open(self, job_id: str, epoch: int):
        with self.journal.transaction() as db:
            old = self.journal.get("admission", "gate", db)
            if (
                old is None
                or old["job_id"] != job_id
                or old["epoch"] != epoch
                or db.execute("SELECT 1 FROM records WHERE kind='accepted_work'").fetchone()
            ):
                raise UpdateError("recovery_required")
            self.journal.put("admission", "gate", {**old, "closed": False}, db)
        self.journal.flush_export()

    def admit(self):
        identity = "work-" + uuid.uuid4().hex
        with self.journal.transaction() as db:
            gate = self.journal.get("admission", "gate", db)
            if gate is None or gate["closed"]:
                raise UpdateError("maintenance")
            self.journal.put(
                "accepted_work",
                identity,
                {"id": identity, "outcome": "active", "epoch": gate["epoch"]},
                db,
            )
            self.journal.event(db, "application_work_admitted", identity)
        self.journal.flush_export()
        return identity

    def finish(self, identity: str, *, known: bool):
        with self.journal.transaction() as db:
            work = self.journal.get("accepted_work", identity, db)
            if work is None:
                raise UpdateError("operation_conflict")
            if known:
                db.execute("DELETE FROM records WHERE kind='accepted_work' AND id=?", (identity,))
                self.journal.event(db, "application_work_finished", identity)
            else:
                self.journal.put("accepted_work", identity, {**work, "outcome": "unknown"}, db)
                self.journal.event(db, "application_work_unknown", identity)
        self.journal.flush_export()

    @contextlib.contextmanager
    def work(self):
        identity = self.admit()
        ticket = Ticket(identity)
        try:
            yield ticket
        except BaseException:
            self.finish(identity, known=False)
            raise
        else:
            self.finish(identity, known=ticket.known)


def configured() -> Admission | None:
    directory = os.getenv("FLAMORIS_UPDATE_STATE")
    if directory:
        return Admission(Path(directory))
    if os.getenv("FLAMORIS_UPDATE_REQUIRED") == "1":
        raise UpdateError("invalid_profile", "Managed startup requires an owner state binding")
    return None


class LifecycleLease:
    """Keep long-lived CLI sessions accepted through their final DB cleanup."""

    def __init__(self):
        self.gate = None if CURRENT.get() else configured()
        self.identity = None if self.gate is None else self.gate.admit()

    def finish(self, *, known: bool):
        if self.identity is not None:
            identity, self.identity = self.identity, None
            self.gate.finish(identity, known=known)


def register_boot(application_id: str) -> None:
    if CURRENT.get() == "owner-maintenance":
        return
    gate = configured()
    if gate is None:
        return
    from importlib.metadata import version

    state = gate.state()
    with gate.journal.transaction() as db:
        gate.journal.put(
            "application_boot",
            application_id,
            {
                "application_id": application_id,
                "release": version(application_id),
                "epoch": state["epoch"],
                "job_id": state["job_id"],
                "started_at": int(time.time()),
                "boot_id": "boot-" + uuid.uuid4().hex,
            },
            db,
        )
        gate.journal.event(db, "application_boot", application_id)
    gate.journal.flush_export()


def wait_for_admission(application_id: str) -> None:
    """Start a managed service without opening DB/provider writers during update.

    The independent Owner remains reachable while the product waits. Only the
    authorized update job reopens admission; neither elapsed time nor startup
    can do it. CLI writers use guarded(), rather than this service-only wait.
    """
    if CURRENT.get() == "owner-maintenance":
        return
    gate = configured()
    if gate is None:
        return
    register_boot(application_id)
    while gate.state()["closed"]:
        time.sleep(0.2)


def guarded(
    error_factory: Callable[[str], Exception] | None = None, *, rejection=None
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Fence a complete application operation, including cleanup and streaming.

    Unmanaged installations retain their existing behavior. The managed service
    profile sets REQUIRED=1; a missing or corrupt binding then fails closed.
    """
    import inspect

    def decorate(function: Callable[P, R]) -> Callable[P, R]:
        def context():
            try:
                gate = None if CURRENT.get() else configured()
                return contextlib.nullcontext() if gate is None else gate.work()
            except UpdateError as error:
                if error_factory is not None:
                    raise error_factory("maintenance") from None
                raise error

        @contextlib.contextmanager
        def boundary():
            token = None
            try:
                with context() as ticket:
                    if ticket is not None:
                        token = CURRENT.set(ticket.identity)
                    yield ticket
            except UpdateError:
                if error_factory is not None:
                    raise error_factory("maintenance") from None
                raise
            finally:
                if token is not None:
                    CURRENT.reset(token)

        def observe(ticket: Ticket | None, result: Any) -> None:
            if ticket is not None and isinstance(result, dict) and result.get("ok") is False:
                error = result.get("error")
                code = error.get("code") if isinstance(error, dict) else error
                if code in UNCERTAIN:
                    ticket.known = False

        if inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def asynchronous(*args, **kwargs):
                try:
                    with boundary() as ticket:
                        result = await function(*args, **kwargs)
                        observe(ticket, result)
                        return result
                except UpdateError:
                    if rejection is not None:
                        return rejection()
                    raise

            return cast(Callable[P, R], asynchronous)

        @functools.wraps(function)
        def synchronous(*args, **kwargs):
            try:
                with boundary() as ticket:
                    result = function(*args, **kwargs)
                    observe(ticket, result)
                    return result
            except UpdateError:
                if rejection is not None:
                    return rejection()
                raise

        return synchronous

    return decorate
