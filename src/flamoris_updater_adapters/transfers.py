"""Bounded installation-support transfers; uploaded bytes never become execution inputs."""

import base64
import binascii
import hashlib
import os
import stat
import time
import uuid
from contextlib import contextmanager
from typing import Annotated

from pydantic import Field, field_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Digest, Model
from flamoris_update_core.wire import digest, loads

from .journal import exclusive, protected_dir

CHUNK_BYTES = 128 * 1024
MAX_FILE_BYTES = 1024**3
MAX_RESERVED_BYTES = 4 * 1024**3
MAX_FILES = 128
RESERVE_BYTES = 256 * 1024**2
TransferId = Annotated[
    str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
]


class Transfer(Model):
    transfer_id: TransferId

    @field_validator("transfer_id")
    @classmethod
    def canonical_id(cls, value):
        if str(uuid.UUID(value)) != value:
            raise ValueError("A canonical transfer UUID is required")
        return value


class Begin(Transfer):
    application_id: ID
    file_name: str = Field(min_length=1, max_length=180)
    size_bytes: int = Field(ge=0, le=MAX_FILE_BYTES)
    sha256: Digest

    @field_validator("file_name")
    @classmethod
    def leaf_name(cls, value):
        if value in {".", ".."} or any(c in "/\\" or ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("A filename, not a path, is required")
        return value


class Write(Transfer):
    offset: int = Field(ge=0, le=MAX_FILE_BYTES)
    data_base64: str = Field(min_length=1, max_length=4 * ((CHUNK_BYTES + 2) // 3))
    chunk_sha256: Digest


class Read(Transfer):
    offset: int = Field(default=0, ge=0, le=MAX_FILE_BYTES)
    length: int = Field(default=CHUNK_BYTES, ge=1, le=CHUNK_BYTES)


class Release(Transfer):
    sha256: Digest


class ListTransfers(Model):
    cursor: TransferId | None = None
    limit: int = Field(default=25, ge=1, le=100)


TRANSFER_TOOLS = {
    "updater_transfers_list": (
        ListTransfers,
        "List staged installation-support transfers and limits",
        "read",
    ),
    "updater_transfer_begin": (
        Begin,
        "Reserve an immutable installation-support upload; never executes it",
        "stage",
    ),
    "updater_transfer_write": (
        Write,
        "Append one digest-checked chunk; retry the identical pending/last chunk",
        "stage",
    ),
    "updater_transfer_finish": (
        Transfer,
        "Verify and seal an upload; does not extract, install or execute it",
        "stage",
    ),
    "updater_transfer_get": (Transfer, "Inspect one durable installation-support transfer", "read"),
    "updater_transfer_read": (
        Read,
        "Read up to 128 KiB of a verified transfer with chunk and file digests",
        "read",
    ),
    "updater_transfer_release": (
        Release,
        "Release only this staged copy, retaining its immutable receipt",
        "execute",
    ),
}


def fingerprint(info):
    return [info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns]


class Transfers:
    def __init__(self, journal):
        self.journal = journal
        self.root = journal.directory / "transfers"

    @contextmanager
    def directory(self, name=None):
        # Manager's parent is already protected. Refuse symbolic ancestors too,
        # including standalone/test uses; callers can never choose this path.
        if self.root.absolute() != self.root.resolve():
            raise UpdateError("unsafe_storage")
        protected_dir(self.root)
        root = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptor = None
        try:
            self.check_directory(root)
            descriptor = (
                root
                if name is None
                else os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root)
            )
            self.check_directory(descriptor)
            yield descriptor
        finally:
            if descriptor is not None and descriptor != root:
                os.close(descriptor)
            os.close(root)

    @staticmethod
    def check_directory(fd):
        info = os.fstat(fd)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise UpdateError("unsafe_storage")

    @contextmanager
    def payload(self, record, *, write=False, create=False):
        with self.directory(record["transfer_id"]) as directory:
            flags = (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW | os.O_NONBLOCK
            if create:
                flags |= os.O_CREAT | os.O_EXCL
            fd = os.open("payload", flags, 0o600, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_nlink != 1
                    or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) not in {0o400, 0o600}
                    or info.st_size > record["size_bytes"]
                ):
                    raise UpdateError("unsafe_storage")
                yield fd
            finally:
                os.close(fd)

    def record(self, identity):
        record = self.journal.get("installation_transfer", identity)
        if record is None:
            raise UpdateError("transfer_not_found")
        return record

    def save(self, record, event):
        with self.journal.transaction() as db:
            self.journal.put("installation_transfer", record["transfer_id"], record, db)
            self.journal.event(db, event, record["transfer_id"])

    @staticmethod
    def receipt(record):
        return {
            key: record[key]
            for key in (
                "transfer_id",
                "application_id",
                "file_name",
                "size_bytes",
                "sha256",
                "phase",
                "received_bytes",
                "created_at",
                "pending_chunk",
            )
        }

    def invoke(self, name, args):
        try:
            with exclusive(self.journal.directory / "transfers.lock"):
                if name == "updater_transfers_list":
                    return self.list(args)
                record = self.journal.get("installation_transfer", args.transfer_id)
                if name == "updater_transfer_begin":
                    return self.begin(args, record)
                record = self.record(args.transfer_id)
                if name == "updater_transfer_get":
                    return self.receipt(record)
                if name == "updater_transfer_release":
                    return self.release(args, record)
                if name == "updater_transfer_write":
                    return self.write(args, record)
                if name == "updater_transfer_finish":
                    return self.finish(record)
                if name == "updater_transfer_read":
                    return self.read(args, record)
                raise UpdateError("invalid_input")
        except OSError:
            raise UpdateError(
                "transfer_storage_unavailable",
                "Inspect transfer status before retrying the same request",
            ) from None

    def usage(self):
        with self.journal.connection() as db:
            count, reserved = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(json_extract(payload,'$.size_bytes')),0) "
                "FROM records WHERE kind='installation_transfer' "
                "AND json_extract(payload,'$.phase')!='released'"
            ).fetchone()
        return {"files": count, "reserved_bytes": reserved}

    def list(self, args):
        with self.journal.connection() as db:
            rows = db.execute(
                "SELECT id,payload FROM records WHERE kind='installation_transfer' "
                "AND id>? AND json_extract(payload,'$.phase')!='released' ORDER BY id LIMIT ?",
                (args.cursor or "", args.limit + 1),
            ).fetchall()
        return {
            "root_id": "installation-transfers",
            "storage_directory": str(self.root),
            "limits": {
                "chunk_bytes": CHUNK_BYTES,
                "file_bytes": MAX_FILE_BYTES,
                "reserved_bytes": MAX_RESERVED_BYTES,
                "files": MAX_FILES,
                "free_reserve_bytes": RESERVE_BYTES,
            },
            "usage": self.usage(),
            "items": [self.receipt(loads(row["payload"])) for row in rows[: args.limit]],
            "next_cursor": rows[args.limit - 1]["id"] if len(rows) > args.limit else None,
        }

    def begin(self, args, record):
        binding = args.model_dump()
        if record is not None:
            if any(record[k] != v for k, v in binding.items()):
                raise UpdateError("operation_conflict")
            if record["phase"] != "allocating":
                return self.receipt(record)
        else:
            usage = self.usage()
            with self.directory() as directory:
                free = os.fstatvfs(directory)
                if (
                    usage["files"] >= MAX_FILES
                    or usage["reserved_bytes"] + args.size_bytes > MAX_RESERVED_BYTES
                    or free.f_bavail * free.f_frsize
                    < RESERVE_BYTES + usage["reserved_bytes"] + args.size_bytes
                ):
                    raise UpdateError("quota_exceeded")
            record = {
                **binding,
                "phase": "allocating",
                "received_bytes": 0,
                "pending_chunk": None,
                "last_chunk": None,
                "created_at": int(time.time()),
            }
            self.save(record, "transfer_reserved")
        with self.directory() as directory:
            try:
                os.mkdir(args.transfer_id, 0o700, dir_fd=directory)
            except FileExistsError:
                pass
            with self.directory(args.transfer_id) as child:
                contents = os.listdir(child)
                if contents not in ([], ["payload"]):
                    raise UpdateError("unsafe_storage")
                with self.payload(record, write=True, create=not contents) as fd:
                    if os.fstat(fd).st_size != 0:
                        raise UpdateError("unsafe_storage")
                    os.fsync(fd)
                os.fsync(child)
            os.fsync(directory)
        record["phase"] = "receiving"
        self.save(record, "transfer_opened")
        return self.receipt(record)

    def write(self, args, record):
        try:
            data = base64.b64decode(args.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise UpdateError("invalid_input") from None
        if not data or len(data) > CHUNK_BYTES or digest(data) != args.chunk_sha256:
            raise UpdateError("artifact_mismatch")
        end = args.offset + len(data)
        chunk = {"offset": args.offset, "size_bytes": len(data), "sha256": args.chunk_sha256}
        if record["phase"] != "receiving" or end > record["size_bytes"]:
            raise UpdateError("transfer_incomplete")
        with self.payload(record, write=True) as fd:
            size = os.fstat(fd).st_size
            if args.offset < record["received_bytes"] and record["pending_chunk"] is None:
                if (
                    record["last_chunk"] != chunk
                    or size != record["received_bytes"]
                    or os.pread(fd, len(data), args.offset) != data
                ):
                    raise UpdateError("operation_conflict")
                return self.receipt(record)
            if args.offset != record["received_bytes"] or not args.offset <= size <= end:
                raise UpdateError("operation_conflict")
            if record["pending_chunk"] is None:
                if size != args.offset:
                    raise UpdateError("transfer_incomplete")
                record["pending_chunk"] = chunk
                self.save(record, "transfer_chunk_intent")
            if (
                record["pending_chunk"] != chunk
                or os.pread(fd, size - args.offset, args.offset) != data[: size - args.offset]
            ):
                raise UpdateError("operation_conflict")
            free = os.fstatvfs(fd)
            if free.f_bavail * free.f_frsize < RESERVE_BYTES + len(data):
                raise UpdateError("quota_exceeded")
            written = size - args.offset
            while written < len(data):
                count = os.pwrite(fd, data[written:], args.offset + written)
                if count <= 0:
                    raise UpdateError("transfer_storage_unavailable")
                written += count
            os.fsync(fd)
        record.update(received_bytes=end, pending_chunk=None, last_chunk=chunk)
        self.save(record, "transfer_chunk_confirmed")
        return self.receipt(record)

    def finish(self, record):
        if record["phase"] == "ready":
            with self.payload(record) as fd:
                self.sealed(record, fd)
            return self.receipt(record)
        if (
            record["phase"] != "receiving"
            or record["pending_chunk"] is not None
            or record["received_bytes"] != record["size_bytes"]
        ):
            raise UpdateError("transfer_incomplete")
        with self.payload(record) as fd:
            if os.fstat(fd).st_size != record["size_bytes"]:
                raise UpdateError("transfer_incomplete")
            h = hashlib.sha256()
            while data := os.read(fd, 1024 * 1024):
                h.update(data)
            if "sha256:" + h.hexdigest() != record["sha256"]:
                record["phase"] = "mismatch"
                self.save(record, "transfer_digest_mismatch")
                raise UpdateError("artifact_mismatch")
            os.fchmod(fd, 0o400)
            os.fsync(fd)
            record.update(phase="ready", fingerprint=fingerprint(os.fstat(fd)))
        self.save(record, "transfer_verified")
        return self.receipt(record)

    @staticmethod
    def sealed(record, fd):
        if fingerprint(os.fstat(fd)) != record["fingerprint"]:
            raise UpdateError("artifact_mismatch")

    def read(self, args, record):
        if record["phase"] != "ready" or args.offset > record["size_bytes"]:
            raise UpdateError("transfer_incomplete")
        with self.payload(record) as fd:
            self.sealed(record, fd)
            data = os.pread(fd, args.length, args.offset)
            self.sealed(record, fd)
        return {
            **self.receipt(record),
            "offset": args.offset,
            "data_base64": base64.b64encode(data).decode("ascii"),
            "chunk_sha256": digest(data),
            "eof": args.offset + len(data) == record["size_bytes"],
        }

    def release(self, args, record):
        if args.sha256 != record["sha256"]:
            raise UpdateError("operation_conflict")
        if record["phase"] == "released":
            return self.receipt(record)
        record.update(phase="releasing", pending_chunk=None)
        self.save(record, "transfer_release_intent")
        with self.directory() as directory:
            if record["transfer_id"] in os.listdir(directory):
                with self.directory(record["transfer_id"]) as child:
                    contents = os.listdir(child)
                    if contents not in ([], ["payload"]):
                        raise UpdateError("unsafe_storage")
                    if contents:
                        with self.payload(record):
                            pass
                        os.unlink("payload", dir_fd=child)
                    os.fsync(child)
                os.rmdir(record["transfer_id"], dir_fd=directory)
                os.fsync(directory)
        record["phase"] = "released"
        self.save(record, "transfer_released")
        return self.receipt(record)
