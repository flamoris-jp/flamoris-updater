"""Evidence persistence, bounded reading and secret-safe failure classification."""

import os
import sys

import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.diagnostics import Log, effect, failure, recording
from flamoris_updater_adapters.install import run
from flamoris_updater_adapters.journal import Journal

JOB = "job-" + "a" * 32


def test_durable_nested_steps_pagination_and_private_export(tmp_path):
    journal = Journal(tmp_path / "state")
    with recording(journal, JOB, ["hidden-value"]):
        effect("stage", lambda: effect("copy", lambda: None, {"path": "/hidden-value/file"}))
    reopened = Journal(tmp_path / "state")
    first = Log(reopened, JOB).page(0, 2)
    assert first["has_more"] and first["next_after"] == 2
    second = Log(reopened, JOB).page(first["next_after"], 2)
    assert second["complete"] and second["last_sequence"] == 4
    assert second["next_after"] is None
    entries = first["items"] + second["items"]
    assert [e["outcome"] for e in entries] == ["intent", "intent", "completed", "completed"]
    assert entries[1]["step"] == "stage/copy"
    assert entries[1]["details"]["path"] == "/[redacted]/file"
    export = tmp_path / "state/diagnostics" / (JOB + ".jsonl")
    assert [loads(line) for line in export.read_bytes().splitlines()] == entries
    assert export.stat().st_mode & 0o777 == 0o600
    assert export.parent.stat().st_mode & 0o777 == 0o700


def test_diagnostic_intent_export_failure_prevents_effect(tmp_path, monkeypatch):
    journal = Journal(tmp_path / "state")
    calls = []

    def unwritable(*_args, **_kwargs):
        raise OSError(28, "private filesystem detail")

    monkeypatch.setattr("flamoris_updater_adapters.diagnostics.durable_write", unwritable)
    with recording(journal, JOB), pytest.raises(OSError):
        effect("switch", lambda: calls.append("effect"))
    assert calls == []
    # The DB commit survives even when the offline mirror cannot be exported.
    assert Log(journal, JOB).page(0, 50)["items"][0]["outcome"] == "intent"


def test_quota_prevents_effect_without_truncating_existing_evidence(tmp_path, monkeypatch):
    from flamoris_updater_adapters import diagnostics

    monkeypatch.setattr(diagnostics, "MAX_EVENTS", 1)
    calls = []
    with recording(Journal(tmp_path / "state"), JOB) as log:
        log.append("first", "recorded")
        with pytest.raises(UpdateError) as error:
            effect("switch", lambda: calls.append("effect"))
        assert error.value.code == "quota_exceeded"
        assert len(log.page(0, 50)["items"]) == 1
    assert calls == []


def test_command_failure_records_exit_and_fixed_hint_without_output(tmp_path):
    with recording(Journal(tmp_path / "state"), JOB) as log:
        with pytest.raises(UpdateError) as error:
            effect(
                "command",
                lambda: run(
                    [
                        sys.executable,
                        "-c",
                        "import sys; sys.stderr.write('password=hidden-value: No space left on device'); sys.exit(17)",
                    ]
                ),
            )
        assert failure(error.value)["exit_code"] == 17
        assert failure(error.value)["hint"] == "storage_full"
        entry = log.page(0, 50)["items"][-1]
        assert entry["outcome"] == "failed"
        assert entry["details"]["kind"] == "nonzero_exit"
        assert b"hidden-value" not in dumps(entry)
        assert b"sys.stderr" not in dumps(entry)


def test_timeout_os_and_untrusted_exception_attributes_are_typed():
    with pytest.raises(UpdateError) as timeout:
        run([sys.executable, "-c", "import time; time.sleep(2)"], timeout=0.01)
    assert failure(timeout.value)["kind"] == "timeout"
    # The real runner uses integer seconds; a floating timeout isn't serialized.
    with pytest.raises(UpdateError) as absent:
        run(["/missing/updater-test-command"])
    assert failure(absent.value)["hint"] == "missing_path"
    error = RuntimeError("password=hidden-value")
    error.diagnostic = {"kind": "hidden-value", "hint": "hidden-value", "exit_code": "hidden-value"}
    assert b"hidden-value" not in dumps(failure(error))
    assert failure(OSError(13, "hidden-value"))["errno"] == 13
    assert os.path.isabs(sys.executable)
