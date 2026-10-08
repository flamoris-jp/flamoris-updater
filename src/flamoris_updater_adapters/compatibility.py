"""Stdlib-only, read-only v1 control-store probe; runnable from an indexed candidate bundle."""

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path

TABLES = {
    "meta": ["key", "value"],
    "records": ["kind", "id", "payload", "revision"],
    "plans": ["id", "digest", "payload"],
    "blobs": ["id", "payload"],
    "requests": ["subject", "action", "key", "digest", "result_id"],
    "jobs": ["id", "plan_id", "state", "revision", "payload"],
    "claims": ["kind", "id", "job_id"],
    "operations": ["id", "job_id", "binding", "payload", "outcome", "result"],
    "events": ["sequence", "payload", "digest"],
}


def inspect_control(directory):
    path = Path(directory).absolute() / "journal.sqlite"
    if path.is_symlink() or not path.is_file():
        raise ValueError("unsupported control store")
    fingerprint = hashlib.sha256()
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
        db.execute("BEGIN")
        if (
            db.execute("PRAGMA user_version").fetchone()[0] != 1
            or db.execute("PRAGMA quick_check").fetchone()[0] != "ok"
        ):
            raise ValueError("unsupported journal")
        if db.execute("SELECT value FROM meta WHERE key='format'").fetchone() != ("1",):
            raise ValueError("unsupported control format")
        if {
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
        } != set(TABLES):
            raise ValueError("unsupported control tables")
        for table, columns in TABLES.items():
            if [row[1] for row in db.execute(f"PRAGMA table_info({table})")] != columns:
                raise ValueError("unsupported control schema")
            # Hash every authoritative record. Keep all secrets inside the one-way digest.
            for row in db.execute(f"SELECT * FROM {table} ORDER BY 1,2"):
                if table == "meta" and row[0] in {"mode", "epoch"}:
                    continue
                for value in row:
                    data = value if isinstance(value, bytes) else str(value).encode()
                    fingerprint.update(len(data).to_bytes(8, "big") + data)
        epoch = int(db.execute("SELECT value FROM meta WHERE key='epoch'").fetchone()[0])
    return {
        "compatible": True,
        "journal_version": 1,
        "control_store_version": 1,
        "recovery_protocol_version": 1,
        "epoch": epoch,
        "control_digest": "sha256:" + fingerprint.hexdigest(),
    }


def bundle_metadata(directory):
    path = Path(directory) / "bundle-compatibility.json"
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("missing compatibility metadata")
    obj = json.loads(path.read_bytes())
    if (
        set(obj)
        != {
            "compatibility_version",
            "journal_version",
            "control_store_version",
            "recovery_protocol_version",
            "package",
            "version",
        }
        or any(
            type(obj[k]) is not int or obj[k] != 1
            for k in [
                "compatibility_version",
                "journal_version",
                "control_store_version",
                "recovery_protocol_version",
            ]
        )
        or obj["package"] != "flamoris-updater"
        or not isinstance(obj["version"], str)
    ):
        raise ValueError("unsupported compatibility metadata")
    return obj


def probe_candidate(directory, state, command, interpreter):
    import os
    import stat

    executable = Path(interpreter)
    info = executable.stat()
    if (
        not executable.is_absolute()
        or executable.is_symlink()
        or not stat.S_ISREG(info.st_mode)
        or info.st_uid not in {0, os.geteuid()}
        or info.st_mode & 0o7022
    ):
        raise ValueError("unprotected Python interpreter")
    directory = Path(directory)
    metadata = bundle_metadata(directory)
    probe = directory / "site-packages/flamoris_updater_adapters/compatibility.py"
    if probe.is_symlink() or not probe.is_file():
        raise ValueError("missing indexed candidate probe")
    before = inspect_control(state)
    output = command([interpreter, "-I", str(probe), "--state", str(state)], timeout=30)
    candidate = json.loads(output)
    after = inspect_control(state)
    if candidate != before or after != before:
        raise ValueError("candidate control-store probe disagrees")
    return {**candidate, "package_version": metadata["version"]}


def main():
    parser = argparse.ArgumentParser(
        description="Read-only Updater control-store compatibility probe"
    )
    parser.add_argument("--state", required=True)
    args = parser.parse_args()
    import sys

    if sys.version_info[:2] != (3, 12):
        raise SystemExit("Python 3.12 is required")
    try:
        print(json.dumps(inspect_control(args.state), sort_keys=True, separators=(",", ":")))
    except Exception:
        raise SystemExit("Control store is incompatible or unavailable") from None


if __name__ == "__main__":
    main()
