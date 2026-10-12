import threading
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import decode, dumps
from flamoris_updater_adapters.inputs import TOOLS, Facade
from flamoris_updater_adapters.journal import Journal
from flamoris_updater_adapters.managed import MANAGED_TOOLS
from flamoris_updater_adapters.web import create_app

ORIGIN = "https://updater.example.invalid"


def fake_coordinator(tmp_path):
    def invoke(subject, name, payload):
        if name not in MANAGED_TOOLS:
            raise UpdateError("invalid_input")
        decode(MANAGED_TOOLS[name][0], dumps(payload))
        return {"items": []}

    return SimpleNamespace(
        journal=Journal(tmp_path),
        managed_invoke=invoke,
        stopping=threading.Event(),
        wakeup=threading.Event(),
    )


@pytest.fixture
def web(tmp_path):
    c = fake_coordinator(tmp_path)
    with TestClient(create_app(c, ORIGIN, run_worker=False), base_url=ORIGIN) as client:
        yield client


def mcp_call(client, token, method, params=None, identity=1, *, path="/mcp"):
    payload = {"jsonrpc": "2.0", "id": identity, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post(
        path,
        json=payload,
        headers={
            "Accept": "application/json, text/event-stream",
        },
    )


def test_screen_and_api_work_without_account_cookies_or_tokens(web):
    assert web.get("/").status_code == 200
    response = web.post("/api/v1/tools/updater_apps_list", json={})
    assert response.status_code == 200
    assert "set-cookie" not in response.headers
    assert not web.cookies
    for endpoint in [
        "login",
        "logout",
        "session",
        "bootstrap",
        "setup",
        "token",
        "integrations",
        "grants",
    ]:
        assert web.post("/api/v1/" + endpoint, json={}).status_code == 404
    assert web.get("/", headers={"Host": "evil.invalid"}).status_code == 403
    assert (
        web.post(
            "/api/v1/tools/updater_apps_list", json={}, headers={"Origin": "https://evil.invalid"}
        ).status_code
        == 403
    )


def test_mcp_has_no_auth_and_validates_the_same_tools(web):
    response = mcp_call(web, "", "tools/list")
    assert response.status_code == 200
    assert {tool["name"] for tool in response.json()["result"]["tools"]} == set(MANAGED_TOOLS)
    bad = mcp_call(
        web,
        "",
        "tools/call",
        {"name": "updater_apps_list", "arguments": {"command": "private-do-not-echo"}},
    ).json()["result"]
    assert bad["isError"] and "private-do-not-echo" not in dumps(bad).decode()


@pytest.mark.parametrize("name", list(TOOLS))
def test_every_adapter_uses_strict_same_input_contract(environment, name):
    with pytest.raises(Exception):
        Facade(environment.coordinator).invoke("operator", name, {"command": "never-accepted"})


@pytest.mark.parametrize("name", ["updater_enrollment_plan", "updater_enroll_execute"])
def test_removed_import_tools_rejected_by_web_and_mcp(web, name):
    assert web.post("/api/v1/tools/" + name, json={}).status_code == 409
    assert mcp_call(web, "", "tools/call", {"name": name, "arguments": {}}).json()["result"][
        "isError"
    ]
