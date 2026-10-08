import datetime as dt
from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.models import ID, Digest, Manifest, Model
from flamoris_update_core.wire import decode, digest, dumps, loads, version

from .journal import Journal
from .signing import Key, verify


class CatalogEntry(Model):
    release: str
    manifest_locator: Annotated[str, StringConstraints(min_length=1, max_length=2048)]
    manifest_digest: Digest
    published_at: str
    withdrawn: bool
    reason: Annotated[str, StringConstraints(max_length=4096)]


class Catalog(Model):
    catalog_version: Literal[1]
    application_id: ID
    channel: ID
    sequence: int = Field(gt=0)
    expires_at: str
    releases: list[CatalogEntry] = Field(max_length=2048)

    @model_validator(mode="after")
    def entries(self):
        if len({e.release for e in self.releases}) != len(self.releases) or len(
            {e.manifest_digest for e in self.releases}
        ) != len(self.releases):
            raise ValueError("duplicate catalog mapping")
        timestamp(self.expires_at)
        for entry in self.releases:
            version(entry.release)
            timestamp(entry.published_at)
        return self


def timestamp(text: str) -> int:
    instant = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    if instant.tzinfo != dt.timezone.utc:
        raise ValueError("UTC timestamp required")
    return int(instant.timestamp())


def validate_notes(manifest: Manifest, human: bytes, changes: bytes):
    if (
        len(human) > 1024 * 1024
        or len(changes) > 1024 * 1024
        or digest(human) != manifest.release_notes.human.digest
        or digest(changes) != manifest.release_notes.changes.digest
    ):
        raise UpdateError("invalid_manifest", "Release notes failed digest/size verification")
    try:
        human.decode("utf-8", errors="strict")
        obj = loads(changes)
        if (
            set(obj)
            != {
                "format_version",
                "application_id",
                "release",
                "entries",
                "restart_required",
                "recovery_conditions",
            }
            or type(obj["format_version"]) is not int
            or obj["format_version"] != 1
            or obj["application_id"] != manifest.application_id
            or obj["release"] != manifest.release
            or type(obj["restart_required"]) is not bool
            or not isinstance(obj["recovery_conditions"], str)
        ):
            raise ValueError("notes shape")
        if not isinstance(obj["entries"], list) or len(obj["entries"]) > 1024:
            raise ValueError("entry limit")
        for entry in obj["entries"]:
            if (
                set(entry) != {"category", "summary", "affected", "breaking"}
                or entry["category"]
                not in {"feature", "fix", "compatibility", "migration", "security", "known_issue"}
                or not isinstance(entry["summary"], str)
                or not isinstance(entry["affected"], list)
                or any(not isinstance(x, str) for x in entry["affected"])
                or type(entry["breaking"]) is not bool
            ):
                raise ValueError("entry shape")
    except (ValueError, TypeError, UnicodeError):
        raise UpdateError("invalid_manifest", "Invalid structured release notes") from None


class ReleaseStore:
    def __init__(
        self,
        journal: Journal,
        keys: dict[str, Key],
        clock,
        channel_keys: dict[str, list[str]] | None = None,
    ):
        self.journal, self.keys, self.clock = journal, keys, clock
        self.channel_keys = channel_keys or {}
        self.refresh = lambda application, channel="stable": None
        self.ensure = lambda identity: None

    def accept_catalog(self, application: str, channel: str, raw: bytes, signature: bytes):
        keys = {
            k: v
            for k, v in self.keys.items()
            if k in self.channel_keys.get(channel, list(self.keys))
        }
        verify(raw, signature, keys, application, "catalog")
        catalog = decode(Catalog, raw)
        obj = loads(raw)
        if (
            type(obj["catalog_version"]) is not int
            or catalog.application_id != application
            or catalog.channel != channel
            or timestamp(catalog.expires_at) <= self.clock()
        ):
            raise UpdateError("untrusted_release", "Catalog scope, clock or expiry failed")
        identity = application + "." + channel
        with self.journal.transaction() as db:
            previous = self.journal.get("catalog", identity, db)
            if previous and (
                catalog.sequence < previous["sequence"]
                or (catalog.sequence == previous["sequence"] and digest(raw) != previous["digest"])
            ):
                raise UpdateError("catalog_replay")
            if (
                previous
                and catalog.sequence == previous["sequence"]
                and digest(raw) == previous["digest"]
                and digest(signature) == previous["signature"]
            ):
                return
            for entry in catalog.releases:
                mapping = application + "." + entry.release
                old = self.journal.get("release_mapping", mapping, db)
                if old and old["digest"] != entry.manifest_digest:
                    raise UpdateError("immutable_release_conflict")
                self.journal.put("release_mapping", mapping, {"digest": entry.manifest_digest}, db)
            raw_id = self.journal.store_blob(raw, db)
            signature_id = self.journal.store_blob(signature, db)
            self.journal.put(
                "catalog",
                identity,
                {
                    **catalog.model_dump(),
                    "digest": digest(raw),
                    "raw": raw_id,
                    "signature": signature_id,
                },
                db,
            )
            self.journal.event(db, "catalog_verified", identity)

    def import_release(
        self, application: str, raw: bytes, signature: bytes, human: bytes, changes: bytes
    ) -> str:
        verify(raw, signature, self.keys, application, "release")
        manifest = decode(Manifest, raw)
        if (
            type(loads(raw)["manifest_version"]) is not int
            or manifest.application_id != application
        ):
            raise UpdateError("invalid_manifest")
        validate_notes(manifest, human, changes)
        identity = digest(raw)
        with self.journal.transaction() as db:
            mapping = application + "." + manifest.release
            previous = self.journal.get("release_mapping", mapping, db)
            if previous and previous["digest"] != identity:
                raise UpdateError("immutable_release_conflict")
            self.journal.put("release_mapping", mapping, {"digest": identity}, db)
            blobs = {
                name: self.journal.store_blob(value, db)
                for name, value in {
                    "raw": raw,
                    "signature": signature,
                    "human": human,
                    "changes": changes,
                }.items()
            }
            self.journal.put(
                "release",
                identity,
                {"application_id": application, "release": manifest.release, **blobs},
                db,
            )
            self.journal.event(db, "release_verified", identity)
        return identity

    def get(self, identity: str, channel: str = "stable", eligible: bool = True) -> Manifest:
        record = self.journal.get("release", identity)
        if record is None:
            self.ensure(identity)
            record = self.journal.get("release", identity)
        if record is None:
            raise UpdateError("untrusted_release", "Verified release is unavailable")
        raw, signature = self.journal.blob(record["raw"]), self.journal.blob(record["signature"])
        verify(raw, signature, self.keys, record["application_id"], "release")
        manifest = decode(Manifest, raw)
        if digest(raw) != identity:
            raise UpdateError("untrusted_release")
        if eligible:
            self.refresh(manifest.application_id, channel)
            cat = self.journal.get("catalog", manifest.application_id + "." + channel)
            if cat is None:
                raise UpdateError("untrusted_release", "Current signed catalog is required")
            catalog_raw = self.journal.blob(cat["raw"])
            keys = {
                k: v
                for k, v in self.keys.items()
                if k in self.channel_keys.get(channel, list(self.keys))
            }
            verify(
                catalog_raw,
                self.journal.blob(cat["signature"]),
                keys,
                manifest.application_id,
                "catalog",
            )
            if timestamp(cat["expires_at"]) <= self.clock() or not any(
                e["manifest_digest"] == identity and not e["withdrawn"] for e in cat["releases"]
            ):
                raise UpdateError(
                    "untrusted_release", "Release is withdrawn, absent or catalog expired"
                )
        return manifest

    def _catalog(self, application, channel="stable"):
        cat = self.journal.get("catalog", application + "." + channel)
        if cat is None:
            raise UpdateError("untrusted_release")
        keys = {
            k: v
            for k, v in self.keys.items()
            if k in self.channel_keys.get(channel, list(self.keys))
        }
        verify(
            self.journal.blob(cat["raw"]),
            self.journal.blob(cat["signature"]),
            keys,
            application,
            "catalog",
        )
        return cat

    def candidates(self, application: str, channel: str = "stable") -> list[dict]:
        self.refresh(application, channel)
        cat = self._catalog(application, channel)
        return [
            {
                "release": x["release"],
                "manifest_digest": x["manifest_digest"],
                "withdrawn": x["withdrawn"],
                "stale": timestamp(cat["expires_at"]) <= self.clock(),
            }
            for x in sorted(cat["releases"], key=lambda e: version(e["release"]), reverse=True)
        ]

    def notes(
        self, application: str, start: str, end: str, cursor: str = "", limit: int = 20
    ) -> dict:
        low, high = version(start), version(end)
        if not 1 <= limit <= 100 or low >= high:
            raise UpdateError("invalid_input")
        catalog = self._catalog(application)
        entries = sorted(
            (e for e in catalog["releases"] if low < version(e["release"]) <= high),
            key=lambda e: version(e["release"]),
        )
        binding = digest(
            dumps({"catalog": catalog["digest"], "app": application, "start": start, "end": end})
        ).removeprefix("sha256:")
        index, human_offset, changes_offset = 0, 0, 0
        if cursor:
            try:
                prefix, a, b, c = cursor.split(".")
                if prefix != binding or any(not x.isdecimal() for x in (a, b, c)):
                    raise ValueError("cursor")
                index, human_offset, changes_offset = int(a), int(b), int(c)
                if index >= len(entries):
                    raise ValueError("index")
            except ValueError:
                raise UpdateError(
                    "invalid_input", "Release-note cursor no longer matches this range"
                ) from None
        missing = [
            e["release"]
            for e in entries
            if self.journal.get("release", e["manifest_digest"]) is None
        ]
        results, used = [], 0
        while index < len(entries) and len(results) < limit:
            item = entries[index]
            record = self.journal.get("release", item["manifest_digest"])
            if record is None:
                human, changes = "", ""
            else:
                manifest = self.get(item["manifest_digest"], eligible=False)
                human_raw, changes_raw = (
                    self.journal.blob(record["human"]),
                    self.journal.blob(record["changes"]),
                )
                validate_notes(manifest, human_raw, changes_raw)
                human, changes = human_raw.decode(), changes_raw.decode()
            if human_offset > len(human) or changes_offset > len(changes):
                raise UpdateError("invalid_input")
            # Character boundaries preserve UTF-8. Each chunk is below the total escaped-byte cap.
            human_chunk, changes_chunk = (
                human[human_offset : human_offset + 65536],
                changes[changes_offset : changes_offset + 65536],
            )
            last = human_offset + len(human_chunk) == len(human) and changes_offset + len(
                changes_chunk
            ) == len(changes)
            projected = {
                "release": item["release"],
                "withdrawn": item["withdrawn"],
                "human": human_chunk,
                "changes": changes_chunk,
                "human_offset": human_offset,
                "changes_offset": changes_offset,
                "last_chunk": last,
            }
            size = len(dumps(projected))
            if used + size > 1800 * 1024:
                break
            used += size
            results.append(projected)
            if last:
                index += 1
                human_offset = changes_offset = 0
            else:
                human_offset += len(human_chunk)
                changes_offset += len(changes_chunk)
        next_cursor = (
            f"{binding}.{index}.{human_offset}.{changes_offset}" if index < len(entries) else None
        )
        return {
            "entries": results,
            "complete": not missing
            and next_cursor is None
            and any(e["release"] == end for e in entries),
            "missing": missing,
            "next_cursor": next_cursor,
        }
