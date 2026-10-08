import asyncio

import pytest

from flamoris_update_core.admission import Admission
from flamoris_update_core.asgi import AdmissionMiddleware


@pytest.mark.asyncio
async def test_streaming_remains_admitted_until_body_and_background_finish(tmp_path, monkeypatch):
    path = tmp_path / "state"
    gate = Admission(path)
    gate.open("entry", gate.close("entry"))
    monkeypatch.setenv("FLAMORIS_UPDATE_STATE", str(path))
    sent, release = [], asyncio.Event()

    async def application(scope, receive, send):
        await send({"type": "http.response.start", "status": 200})
        await send({"type": "http.response.body", "body": b"first", "more_body": True})
        await release.wait()
        assert gate.state()["active_work"]
        await send({"type": "http.response.body", "body": b"last"})
        assert gate.state()["active_work"]

    async def send(message):
        sent.append(message)

    task = asyncio.create_task(
        AdmissionMiddleware(application)({"type": "http", "path": "/api/assets"}, None, send)
    )
    while len(sent) < 2:
        await asyncio.sleep(0)
    assert gate.state()["active_work"]
    gate.close("update")
    release.set()
    await task
    assert not gate.state()["active_work"]


@pytest.mark.asyncio
async def test_closed_gate_does_not_call_product_but_keeps_health_available(tmp_path, monkeypatch):
    monkeypatch.setenv("FLAMORIS_UPDATE_STATE", str(tmp_path / "state"))
    called, sent = [], []

    async def application(scope, *_):
        called.append(scope["path"])

    async def send(message):
        sent.append(message)

    middleware = AdmissionMiddleware(application)
    await middleware({"type": "http", "path": "/api/generate"}, None, send)
    assert sent[0]["status"] == 503 and not called
    await middleware({"type": "http", "path": "/api/system/status"}, None, send)
    assert called == ["/api/system/status"]
