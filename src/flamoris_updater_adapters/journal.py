import contextlib
import fcntl
import os
import sqlite3
from pathlib import Path

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps, loads

SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
INSERT INTO meta VALUES('format','1'),('epoch','1'),('mode','active');
CREATE TABLE records(kind TEXT NOT NULL,id TEXT NOT NULL,payload BLOB NOT NULL,revision INTEGER NOT NULL,PRIMARY KEY(kind,id));
CREATE TABLE plans(id TEXT PRIMARY KEY,digest TEXT NOT NULL UNIQUE,payload BLOB NOT NULL);
CREATE TABLE blobs(id TEXT PRIMARY KEY,payload BLOB NOT NULL);
CREATE TABLE requests(subject TEXT NOT NULL,action TEXT NOT NULL,key TEXT NOT NULL,digest TEXT NOT NULL,result_id TEXT NOT NULL,PRIMARY KEY(subject,action,key));
CREATE TABLE jobs(id TEXT PRIMARY KEY,plan_id TEXT NOT NULL UNIQUE,state TEXT NOT NULL,revision INTEGER NOT NULL,payload BLOB NOT NULL);
CREATE TABLE claims(kind TEXT NOT NULL,id TEXT NOT NULL,job_id TEXT NOT NULL,PRIMARY KEY(kind,id));
CREATE TABLE operations(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,binding TEXT NOT NULL,payload BLOB NOT NULL,outcome TEXT NOT NULL,result BLOB);
CREATE TABLE events(sequence INTEGER PRIMARY KEY AUTOINCREMENT,payload BLOB NOT NULL,digest TEXT NOT NULL);
"""


def protected_dir(path: Path) -> None:
    path = Path(path)
    if path.is_symlink():
        raise UpdateError("unsafe_storage")
    path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.stat()
    if info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise UpdateError(
            "unsafe_storage", "State directory must be private and owned by the service"
        )


@contextlib.contextmanager
def exclusive(path: Path, blocking: bool = False):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise UpdateError("busy", "Execution authority is already held") from None
        yield
    finally:
        os.close(fd)


def durable_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    temporary = path.with_name(path.name + ".new")
    fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY | os.O_NOFOLLOW, mode)
    try:
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(data)
            stream.flush()
            os.fsync(fd)
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        os.close(fd)


class Journal:
    def __init__(self, directory: Path):
        self.directory = Path(directory)
        protected_dir(self.directory)
        self.path = self.directory / "journal.sqlite"
        if self.path.is_symlink():
            raise UpdateError("unsafe_storage")
        with exclusive(self.directory / "bootstrap.lock", blocking=True):
            new = not self.path.exists()
            fd = os.open(self.path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            os.close(fd)
            if self.path.stat().st_uid != os.geteuid() or self.path.stat().st_mode & 0o077:
                raise UpdateError("unsafe_storage")
            with self.connection() as db:
                if new:
                    db.executescript(SCHEMA)
                    db.execute("PRAGMA user_version=1")
                if db.execute("PRAGMA user_version").fetchone()[0] != 1:
                    raise UpdateError("unsupported_journal")
                if db.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                    raise UpdateError("journal_corrupt")

    @contextlib.contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA wal_autocheckpoint=256")
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        try:
            with self.connection() as db:
                db.execute("BEGIN IMMEDIATE")
                try:
                    yield db
                    db.execute("COMMIT")
                except BaseException:
                    db.execute("ROLLBACK")
                    raise
        except sqlite3.Error:
            raise UpdateError("journal_unavailable", "Durable journal operation failed") from None

    def get(self, kind: str, identity: str, db=None) -> dict | None:
        if db is None:
            with self.connection() as db:
                return self.get(kind, identity, db)
        row = db.execute(
            "SELECT payload,revision FROM records WHERE kind=? AND id=?", (kind, identity)
        ).fetchone()
        return (
            None
            if row is None
            else {**loads(row["payload"], 2 * 1024 * 1024), "_revision": row["revision"]}
        )

    def put(self, kind: str, identity: str, payload: dict, db, expected: int | None = None):
        payload = {k: v for k, v in payload.items() if k != "_revision"}
        old = self.get(kind, identity, db)
        if expected is not None and (old or {}).get("_revision", 0) != expected:
            raise UpdateError("revision_conflict")
        revision = (old or {}).get("_revision", 0) + 1
        db.execute(
            "INSERT INTO records VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET payload=excluded.payload,revision=excluded.revision",
            (kind, identity, dumps(payload), revision),
        )
        return revision

    def list(self, kind: str, cursor: str = "", limit: int = 100) -> list[dict]:
        if not 1 <= limit <= 100:
            raise UpdateError("invalid_input")
        with self.connection() as db:
            rows = db.execute(
                "SELECT id,payload,revision FROM records WHERE kind=? AND id>? ORDER BY id LIMIT ?",
                (kind, cursor, limit),
            ).fetchall()
            return [
                {**loads(r["payload"], 2 * 1024 * 1024), "id": r["id"], "_revision": r["revision"]}
                for r in rows
            ]

    def meta(self, key: str, db=None) -> str:
        if db is None:
            with self.connection() as db:
                return self.meta(key, db)
        row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        if row is None:
            raise UpdateError("journal_corrupt")
        return row[0]

    def store_blob(self, raw: bytes, db) -> str:
        if len(raw) > 1024 * 1024:
            raise UpdateError("quota_exceeded")
        identity = digest(raw)
        db.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (identity, raw))
        return identity

    def blob(self, identity: str) -> bytes:
        with self.connection() as db:
            row = db.execute("SELECT payload FROM blobs WHERE id=?", (identity,)).fetchone()
        if row is None or digest(row[0]) != identity:
            raise UpdateError("journal_corrupt")
        return row[0]

    def event(self, db, event: str, identity: str, outcome: str = ""):
        previous = db.execute("SELECT digest FROM events ORDER BY sequence DESC LIMIT 1").fetchone()
        payload = dumps(
            {
                "event_version": 1,
                "type": event,
                "id": identity,
                "outcome": outcome,
                "previous": previous[0] if previous else None,
            }
        )
        db.execute("INSERT INTO events(payload,digest) VALUES(?,?)", (payload, digest(payload)))

    def flush_export(self):
        # Serialize exporters and read one SQLite snapshot; never expose records/credentials.
        with exclusive(self.directory / "export.lock", blocking=True):
            with self.connection() as db:
                db.execute("BEGIN")
                rows = db.execute(
                    "SELECT sequence,payload,digest FROM events ORDER BY sequence"
                ).fetchall()
                lines = [
                    dumps(
                        {
                            "sequence": r["sequence"],
                            "digest": r["digest"],
                            **loads(r["payload"], 2 * 1024 * 1024),
                        }
                    )
                    for r in rows
                ]
            durable_write(
                self.directory / "recovery.jsonl", b"\n".join(lines) + (b"\n" if lines else b"")
            )

    def recover_intents(self):
        # Called only while holding the relevant execution-authority process lock.
        with self.transaction() as db:
            rows = db.execute("SELECT id FROM operations WHERE outcome='intent'").fetchall()
            for row in rows:
                db.execute("UPDATE operations SET outcome='unknown' WHERE id=?", (row[0],))
                self.event(db, "operation_interrupted", row[0], "unknown")
        self.flush_export()


def inspect_journal(directory: Path) -> dict:
    """Read-only, does not bootstrap, migrate, checkpoint or clear blockers."""
    path = Path(directory) / "journal.sqlite"
    if path.is_symlink() or not path.is_file():
        raise UpdateError("unsafe_storage")
    uri = path.as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as db:
        if (
            db.execute("PRAGMA user_version").fetchone()[0] != 1
            or db.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        ):
            raise UpdateError("unsupported_journal")
        return {
            "journal_version": 1,
            "jobs": [
                dict(zip(("id", "state", "revision"), row))
                for row in db.execute("SELECT id,state,revision FROM jobs ORDER BY id LIMIT 100")
            ],
            "blocked_resources": [
                dict(zip(("kind", "id", "job_id"), row))
                for row in db.execute(
                    "SELECT kind,id,job_id FROM claims ORDER BY kind,id LIMIT 100"
                )
            ],
            "unsettled_operations": [
                dict(zip(("id", "job_id", "outcome"), row))
                for row in db.execute(
                    "SELECT id,job_id,outcome FROM operations WHERE outcome IN ('intent','unknown','partial_known') ORDER BY id LIMIT 100"
                )
            ],
        }
