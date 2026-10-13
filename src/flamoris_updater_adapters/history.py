"""Bounded read-only job views; insertion order survives progress writes and clock skew."""

import time

from pydantic import Field, model_validator

from flamoris_update_core.models import ID, Model
from flamoris_update_core.wire import loads


class Cursor(Model):
    created_at: int = Field(ge=0, le=253402300799)
    job_id: ID
    ceiling: int = Field(ge=0, le=9223372036854775807)


class History(Model):
    application_id: ID | None = None
    unassigned: bool = False
    created_from: int | None = Field(default=None, ge=0, le=253402300799)
    created_to: int | None = Field(default=None, ge=0, le=253402300799)
    after_sequence: int | None = Field(default=None, ge=0, le=9223372036854775807)
    cursor: Cursor | None = None
    limit: int = Field(default=100, ge=1, le=100)

    @model_validator(mode="after")
    def valid_period(self):
        if self.application_id and self.unassigned:
            raise ValueError("Choose an application or unassigned jobs")
        if (
            self.created_from is not None
            and self.created_to is not None
            and self.created_from >= self.created_to
        ):
            raise ValueError("The end must be after the start; end is exclusive")
        return self


def begin_history(journal):
    with journal.connection() as db:
        db.execute("BEGIN")
        # MAX across all records avoids reuse of a deleted non-job rowid at the boundary.
        boundary = db.execute("SELECT COALESCE(MAX(rowid),0) FROM records").fetchone()[0]
        applications = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT json_extract(payload,'$.application_id') FROM records "
                "WHERE kind='managed_job' AND json_extract(payload,'$.application_id') IS NOT NULL "
                "ORDER BY 1 LIMIT 128"
            )
        ]
        return {
            "after_sequence": boundary,
            "server_time": int(time.time()),
            "applications": applications,
        }


def search_history(journal, args):
    with journal.connection() as db:
        db.execute("BEGIN")
        ceiling = (
            args.cursor.ceiling
            if args.cursor
            else db.execute("SELECT COALESCE(MAX(rowid),0) FROM records").fetchone()[0]
        )
        created = "COALESCE(json_extract(payload,'$.created_at'),0)"
        where, parameters = ["kind='managed_job'", "rowid<=?"], [ceiling]
        if args.after_sequence is not None:
            where.append("rowid>?")
            parameters.append(args.after_sequence)
        if args.application_id:
            where.append("json_extract(payload,'$.application_id')=?")
            parameters.append(args.application_id)
        if args.unassigned:
            where.append("json_extract(payload,'$.application_id') IS NULL")
        for bound, operator in [(args.created_from, ">="), (args.created_to, "<")]:
            if bound is not None:
                where.append(f"{created}{operator}?")
                parameters.append(bound)
        if args.cursor:
            where.append(f"({created}<? OR ({created}=? AND id<?))")
            parameters.extend([args.cursor.created_at, args.cursor.created_at, args.cursor.job_id])
        rows = db.execute(
            f"SELECT id,payload,{created} AS created FROM records WHERE "
            + " AND ".join(where)
            + f" ORDER BY {created} DESC,id DESC LIMIT ?",
            [*parameters, args.limit + 1],
        ).fetchall()
        more = len(rows) > args.limit
        rows = rows[: args.limit]
        next_cursor = (
            {"created_at": rows[-1]["created"], "job_id": rows[-1]["id"], "ceiling": ceiling}
            if more
            else None
        )
        # Old active self jobs remain blockers even when outside the visible window.
        active_self = bool(
            db.execute(
                "SELECT 1 FROM records WHERE kind='managed_job' "
                "AND json_extract(payload,'$.action')='self_update' "
                "AND json_extract(payload,'$.phase') IN ('accepted','running','intent','recovery_required') "
                "LIMIT 1"
            ).fetchone()
        )
        return {
            "items": [loads(r["payload"]) for r in rows],
            "next_cursor": next_cursor,
            "active_self_update": active_self,
        }
