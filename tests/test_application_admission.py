import asyncio

import pytest

from flamoris_update_core.admission import Admission, guarded
from flamoris_update_core.errors import UpdateError


def test_restart_preserves_maintenance_and_unknown_work(tmp_path):
    first = Admission(tmp_path / "state")
    epoch = first.close("entry-job")
    first.open("entry-job", epoch)
    token = first.admit()
    first.finish(token, known=False)
    restarted = Admission(tmp_path / "state")
    restarted.close("update-job")
    assert restarted.state()["unknown_work"]
    with pytest.raises(UpdateError, match="Operation rejected"):
        restarted.open("update-job", restarted.state()["epoch"])


def test_closed_gate_does_not_admit_and_foreign_job_cannot_reopen(tmp_path):
    gate = Admission(tmp_path / "state")
    with pytest.raises(UpdateError):
        gate.admit()
    epoch = gate.close("entry-job")
    with pytest.raises(UpdateError):
        gate.open("foreign-job", epoch)
    gate.open("entry-job", epoch)
    with gate.work():
        with pytest.raises(UpdateError):
            gate.close("other-job") if gate.state()["closed"] else gate.open("entry-job", epoch)
    assert not gate.state()["active_work"]


@pytest.mark.asyncio
async def test_cancelled_await_keeps_durable_uncertainty(tmp_path, monkeypatch):
    path = tmp_path / "state"
    gate = Admission(path)
    gate.open("entry-job", gate.close("entry-job"))
    monkeypatch.setenv("FLAMORIS_UPDATE_STATE", str(path))
    started = asyncio.Event()

    @guarded()
    async def request():
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(request())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert Admission(path).state()["unknown_work"]


def test_managed_startup_cannot_silently_drop_gate(monkeypatch):
    monkeypatch.delenv("FLAMORIS_UPDATE_STATE", raising=False)
    monkeypatch.setenv("FLAMORIS_UPDATE_REQUIRED", "1")

    @guarded()
    def writer():
        return 1

    with pytest.raises(UpdateError):
        writer()
