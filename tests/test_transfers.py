import base64
import io
import os
from types import SimpleNamespace
from uuid import uuid4

import pytest
from starlette.testclient import TestClient

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import decode, digest, dumps
from flamoris_updater_adapters import transfers as t
from flamoris_updater_adapters.journal import Journal, exclusive
from flamoris_updater_adapters.managed import MANAGED_TOOLS, Manager
from flamoris_updater_adapters.web import create_app


@pytest.fixture
def store(tmp_path):
    return t.Transfers(Journal(tmp_path / "manager"))


def call(store, name, **args):
    name = "updater_" + name
    return store.invoke(name, decode(t.TRANSFER_TOOLS[name][0], dumps(args)))


def begin(store, data=b"installation support", **changes):
    args = dict(
        transfer_id=str(uuid4()),
        application_id="example-app",
        file_name="setup.py",
        size_bytes=len(data),
        sha256=digest(data),
    )
    args.update(changes)
    return call(store, "transfer_begin", **args)


def write(store, record, data, offset=0):
    return call(
        store,
        "transfer_write",
        transfer_id=record["transfer_id"],
        offset=offset,
        data_base64=base64.b64encode(data).decode(),
        chunk_sha256=digest(data),
    )


def finish(store, record):
    return call(store, "transfer_finish", transfer_id=record["transfer_id"])


def release(store, record):
    return call(
        store, "transfer_release", transfer_id=record["transfer_id"], sha256=record["sha256"]
    )


def test_roundtrip_chunks_restart_seal_and_release(store):
    data = b"0123456789" * 30000
    record = begin(store, data, file_name="導入補助.py")
    with pytest.raises(UpdateError, match="Operation rejected"):
        call(store, "transfer_read", transfer_id=record["transfer_id"])
    for offset in range(0, len(data), t.CHUNK_BYTES):
        chunk = data[offset : offset + t.CHUNK_BYTES]
        result = write(store, record, chunk, offset)
        assert write(store, record, chunk, offset) == result
    store = t.Transfers(Journal(store.journal.directory))
    receipt = finish(store, record)
    assert finish(store, record) == receipt
    assert receipt["phase"] == "ready"
    parts = []
    for offset in range(0, len(data), 100000):
        part = call(
            store, "transfer_read", transfer_id=record["transfer_id"], offset=offset, length=100000
        )
        raw = base64.b64decode(part["data_base64"])
        assert digest(raw) == part["chunk_sha256"]
        parts.append(raw)
    assert b"".join(parts) == data
    assert digest(b"".join(parts)) == receipt["sha256"]
    with pytest.raises(UpdateError):
        write(store, record, b"X", 0)
    listing = call(store, "transfers_list")
    assert listing["usage"] == {"files": 1, "reserved_bytes": len(data)}
    assert listing["limits"]["chunk_bytes"] == t.CHUNK_BYTES
    payload = store.root / record["transfer_id"] / "payload"
    assert payload.stat().st_mode & 0o777 == 0o400
    assert release(store, record)["phase"] == "released"
    assert release(store, record)["phase"] == "released"
    assert not payload.parent.exists()
    assert call(store, "transfers_list")["usage"] == {"files": 0, "reserved_bytes": 0}
    assert (
        begin(store, data, transfer_id=record["transfer_id"], file_name="導入補助.py")["phase"]
        == "released"
    )


@pytest.mark.parametrize(
    "name", ["../setup.py", "/etc/config", "nested/setup.py", "a\\b", "..", "a\0b", "a\nb"]
)
def test_no_destinations_urls_or_invalid_names(store, name):
    with pytest.raises(UpdateError) as e:
        begin(store, file_name=name)
    assert e.value.code == "invalid_input"
    assert not store.journal.list("installation_transfer")


def test_strict_fields_chunks_and_no_payload_echo(store):
    record = begin(store)
    for changes in (
        {"offset": True},
        {"data_base64": "!"},
        {"chunk_sha256": digest(b"wrong")},
        {"offset": 100},
        {"path": "/etc/config"},
        {"data_base64": base64.b64encode(b"x" * (t.CHUNK_BYTES + 1)).decode()},
    ):
        args = dict(
            transfer_id=record["transfer_id"],
            offset=0,
            data_base64=base64.b64encode(b"installation support").decode(),
            chunk_sha256=record["sha256"],
        )
        with pytest.raises(UpdateError):
            call(store, "transfer_write", **(args | changes))
    for changes in (
        {"file_name": "changed.py"},
        {"sha256": digest(b"changed")},
        {"application_id": "another-app"},
    ):
        with pytest.raises(UpdateError) as e:
            begin(store, transfer_id=record["transfer_id"], **changes)
        assert e.value.code == "operation_conflict"
    with store.journal.connection() as db:
        assert b"installation support" not in b"".join(
            r[0] for r in db.execute("SELECT payload FROM events")
        )


def test_empty_file_and_final_digest_mismatch(store):
    empty = begin(store, b"")
    finish(store, empty)
    assert call(store, "transfer_read", transfer_id=empty["transfer_id"])["eof"]
    bad = begin(store, b"expected")
    write(store, bad, b"different"[:8])
    with pytest.raises(UpdateError) as e:
        finish(store, bad)
    assert e.value.code == "artifact_mismatch"
    assert call(store, "transfer_get", transfer_id=bad["transfer_id"])["phase"] == "mismatch"
    release(store, bad)


def test_reservations_pagination_and_quota(store, monkeypatch):
    monkeypatch.setattr(t, "MAX_FILES", 2)
    monkeypatch.setattr(t, "MAX_RESERVED_BYTES", 10)
    a, b = begin(store, b"12345"), begin(store, b"12345")
    with pytest.raises(UpdateError) as e:
        begin(store, b"x")
    assert e.value.code == "quota_exceeded"
    first = call(store, "transfers_list", limit=1)
    second = call(store, "transfers_list", limit=1, cursor=first["next_cursor"])
    assert {first["items"][0]["transfer_id"], second["items"][0]["transfer_id"]} == {
        a["transfer_id"],
        b["transfer_id"],
    }
    assert second["next_cursor"] is None
    release(store, a)
    begin(store, b"12345")
    with exclusive(store.journal.directory / "transfers.lock"):
        with pytest.raises(UpdateError) as e:
            begin(store, b"")
        assert e.value.code == "busy"


def test_full_disk_reserves_fail_before_allocation(store, monkeypatch):
    monkeypatch.setattr(t.os, "fstatvfs", lambda _: SimpleNamespace(f_bavail=0, f_frsize=4096))
    with pytest.raises(UpdateError) as e:
        begin(store)
    assert e.value.code == "quota_exceeded"
    assert not store.journal.list("installation_transfer")


@pytest.mark.parametrize(
    "attack", ["file-symlink", "file-hardlink", "fifo", "directory-symlink", "extra-member"]
)
def test_links_special_files_and_unowned_members_never_followed(store, tmp_path, attack):
    record = begin(store, b"original")
    outside = tmp_path / "outside"
    outside.write_bytes(b"original")
    directory = store.root / record["transfer_id"]
    payload = directory / "payload"
    payload.unlink()
    if attack == "file-symlink":
        payload.symlink_to(outside)
    elif attack == "file-hardlink":
        os.link(outside, payload)
    elif attack == "fifo":
        os.mkfifo(payload, 0o600)
    elif attack == "directory-symlink":
        directory.rmdir()
        directory.symlink_to(tmp_path, target_is_directory=True)
    else:
        payload.touch(mode=0o600)
        (directory / "unrelated").write_bytes(b"keep")
    if attack != "extra-member":
        with pytest.raises(UpdateError):
            write(store, record, b"changed!")
    with pytest.raises(UpdateError):
        release(store, record)
    assert outside.read_bytes() == b"original"
    if attack == "extra-member":
        assert (directory / "unrelated").read_bytes() == b"keep"


def test_private_root_and_sealed_tampering_rejected(store, tmp_path):
    record = begin(store, b"original")
    write(store, record, b"original")
    finish(store, record)
    payload = store.root / record["transfer_id"] / "payload"
    payload.chmod(0o600)
    payload.write_bytes(b"changed!")
    with pytest.raises(UpdateError) as e:
        call(store, "transfer_read", transfer_id=record["transfer_id"])
    assert e.value.code == "artifact_mismatch"
    store.root.chmod(0o755)
    with pytest.raises(UpdateError):
        begin(store, b"new")
    store.root.chmod(0o700)
    other = tmp_path / "other"
    other.mkdir()
    moved = store.root.with_name("moved")
    store.root.rename(moved)
    store.root.symlink_to(other, target_is_directory=True)
    with pytest.raises(UpdateError):
        begin(store, b"new")
    assert not list(other.iterdir())


def test_restart_after_creation_and_written_but_unconfirmed_chunk(store, monkeypatch):
    save = store.save

    def crash(record, event):
        if event in {"transfer_opened", "transfer_chunk_confirmed"}:
            raise RuntimeError("simulated power loss")
        save(record, event)

    monkeypatch.setattr(store, "save", crash)
    identity = str(uuid4())
    with pytest.raises(RuntimeError):
        begin(store, b"payload", transfer_id=identity)
    restarted = t.Transfers(Journal(store.journal.directory))
    record = begin(restarted, b"payload", transfer_id=identity)
    with pytest.raises(RuntimeError):
        write(store, record, b"payload")
    pending = call(restarted, "transfer_get", transfer_id=identity)
    assert pending["pending_chunk"] and pending["received_bytes"] == 0
    with pytest.raises(UpdateError):
        write(restarted, record, b"changed")
    assert write(restarted, record, b"payload")["received_bytes"] == 7
    assert finish(restarted, record)["phase"] == "ready"


def test_retry_exact_partial_chunk_recovers_without_repeating_other_effects(store, monkeypatch):
    record = begin(store, b"payload")
    pwrite = t.os.pwrite
    calls = []

    def partial(fd, data, offset):
        calls.append(offset)
        if len(calls) == 1:
            return pwrite(fd, data[:3], offset)
        raise OSError("simulated interrupted write")

    with monkeypatch.context() as m:
        m.setattr(t.os, "pwrite", partial)
        with pytest.raises(UpdateError):
            write(store, record, b"payload")
    restarted = t.Transfers(Journal(store.journal.directory))
    assert write(restarted, record, b"payload")["received_bytes"] == 7
    finish(restarted, record)
    assert (
        base64.b64decode(
            call(restarted, "transfer_read", transfer_id=record["transfer_id"])["data_base64"]
        )
        == b"payload"
    )


def test_same_actual_manager_dispatch_over_mcp_http_and_cli(tmp_path, monkeypatch):
    import threading

    from flamoris_updater_adapters import cli

    journal = Journal(tmp_path / "manager")
    manager = Manager.__new__(Manager)
    manager.journal = journal
    coordinator = SimpleNamespace(
        journal=journal, stopping=threading.Event(), wakeup=threading.Event()
    )

    def invoke(subject, name, payload):
        if name == "updater_history_begin":
            return {"after_sequence": 0}
        return manager.invoke(name, payload)

    coordinator.managed_invoke = invoke
    origin = "https://updater.example.invalid"
    with TestClient(create_app(coordinator, origin, run_worker=False), base_url=origin) as web:
        identity = str(uuid4())
        payload = dict(
            transfer_id=identity,
            application_id="example-app",
            file_name="setup.sh",
            size_bytes=0,
            sha256=digest(b""),
        )
        assert (
            web.post("/api/v1/tools/updater_transfer_begin", json=payload).json()["phase"]
            == "receiving"
        )
        response = web.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "updater_transfer_finish",
                    "arguments": {"transfer_id": identity},
                },
            },
            headers={"Accept": "application/json, text/event-stream"},
        )
        assert response.json()["result"]["structuredContent"]["phase"] == "ready"
        tools = web.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            headers={"Accept": "application/json, text/event-stream"},
        ).json()["result"]["tools"]
        assert {item["name"] for item in tools} == set(MANAGED_TOOLS)
        annotations = {item["name"]: item["annotations"] for item in tools}
        assert annotations["updater_transfer_read"]["readOnlyHint"]
        assert annotations["updater_transfer_write"]["idempotentHint"]
        assert not annotations["updater_transfer_write"]["destructiveHint"]
        bad = web.post(
            "/api/v1/tools/updater_transfer_begin", json=payload | {"path": "/etc/config"}
        )
        assert bad.status_code == 409 and "config" not in bad.text
        monkeypatch.setattr(cli.Endpoint, "client", lambda _: web)
        output = io.BytesIO()
        monkeypatch.setattr(cli.sys, "stdout", SimpleNamespace(buffer=output))
        arguments = tmp_path / "arguments.json"
        arguments.write_bytes(dumps({"transfer_id": identity}))
        cli.main(
            [
                "call",
                "--url",
                origin,
                "--tool",
                "updater_transfer_get",
                "--arguments",
                str(arguments),
            ]
        )
        assert b'"phase":"ready"' in output.getvalue()


def test_active_self_update_blocks_transfer_mutations_but_keeps_inspection(store):
    manager = Manager.__new__(Manager)
    manager.journal = store.journal
    with store.journal.transaction() as db:
        store.journal.put(
            "managed_job", "self-update", {"action": "self_update", "phase": "running"}, db
        )
    with pytest.raises(UpdateError) as e:
        manager.invoke(
            "updater_transfer_begin",
            dict(
                transfer_id=str(uuid4()),
                application_id="example-app",
                file_name="setup.sh",
                size_bytes=0,
                sha256=digest(b""),
            ),
        )
    assert e.value.code == "busy"
    assert manager.invoke("updater_transfers_list", {})["items"] == []


def test_release_reconciles_interruption_without_removing_other_data(store, monkeypatch):
    record = begin(store, b"payload")
    write(store, record, b"payload")
    finish(store, record)
    save = store.save

    def crash(record, event):
        if event == "transfer_released":
            raise RuntimeError("simulated power loss")
        save(record, event)

    monkeypatch.setattr(store, "save", crash)
    with pytest.raises(RuntimeError):
        release(store, record)
    restarted = t.Transfers(Journal(store.journal.directory))
    assert (
        call(restarted, "transfer_get", transfer_id=record["transfer_id"])["phase"] == "releasing"
    )
    assert release(restarted, record)["phase"] == "released"
    assert call(restarted, "transfers_list")["usage"]["reserved_bytes"] == 0


@pytest.mark.parametrize("mode", [0o644, 0o700, 0o4600, 0o2600])
def test_payload_permissions_never_become_executable_or_shared(store, mode):
    record = begin(store, b"payload")
    payload = store.root / record["transfer_id"] / "payload"
    payload.chmod(mode)
    with pytest.raises(UpdateError):
        write(store, record, b"payload")
    assert payload.read_bytes() == b""
