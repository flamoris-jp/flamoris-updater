import json

import pytest
from starlette.testclient import TestClient

from flamoris_updater_adapters.auth import AuthStore
from flamoris_updater_adapters.inputs import TOOLS, Facade
from flamoris_updater_adapters.web import create_app

ORIGIN = "https://updater.example.invalid"


@pytest.fixture
def web(environment):
    auth = AuthStore(
        environment.coordinator.journal, environment.coordinator.authority, environment.clock
    )
    auth.user(
        "operator",
        "isolated-test-password",
        ["read", "plan", "execute", "enroll", "cancel", "recover_verify", "operator", "recover"],
        ["app"],
    )
    app = create_app(environment.coordinator, auth, ORIGIN, run_worker=False)
    with TestClient(app, base_url=ORIGIN) as client:
        yield client, auth, environment


def login(client):
    bootstrap = client.get("/api/v1/bootstrap").json()
    response = client.post(
        "/api/v1/login",
        json={"username": "operator", "password": "isolated-test-password"},
        headers={"Origin": ORIGIN, "X-CSRF-Token": bootstrap["csrf_token"]},
    )
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def test_dedicated_web_login_cookie_origin_and_csrf(web):
    client, _, _ = web
    assert client.get("/").status_code == 200
    assert "FLAMORIS Updater" in client.get("/").text
    assert (
        client.post(
            "/api/v1/login", json={"username": "operator", "password": "isolated-test-password"}
        ).status_code
        == 403
    )
    csrf = login(client)
    response = client.get("/api/v1/session")
    assert response.json()["subject"] == "operator"
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    payload = {"targets": {"app": web[2].target_id}, "request_key": "web-plan"}
    assert client.post("/api/v1/tools/updater_update_plan", json=payload).status_code == 403
    assert (
        client.post(
            "/api/v1/tools/updater_update_plan",
            json=payload,
            headers={"Origin": "https://evil.example.invalid", "X-CSRF-Token": csrf},
        ).status_code
        == 403
    )
    assert client.get("/", headers={"Host": "evil.example.invalid"}).status_code == 403


def test_web_and_bearer_observe_same_durable_job_logout_keeps_job(web):
    client, auth, e = web
    csrf = login(client)
    h = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    planned = client.post(
        "/api/v1/tools/updater_update_plan",
        json={"targets": {"app": e.target_id}, "request_key": "web-plan"},
        headers=h,
    ).json()
    grant = client.post(
        "/api/v1/grants",
        json={
            "plan_id": planned["plan_id"],
            "plan_digest": planned["plan_digest"],
            "caller_id": "operator",
        },
        headers=h,
    ).json()
    job = client.post(
        "/api/v1/tools/updater_update_execute",
        json={
            "plan_id": planned["plan_id"],
            "plan_digest": planned["plan_digest"],
            "authorization_id": grant["authorization_id"],
            "request_key": "web-start",
        },
        headers=h,
    ).json()
    assert job["state"] == "accepted"
    assert (
        e.coordinator.get_plan("operator", planned["plan_id"])["consumed_job_id"] == job["job_id"]
    )
    assert client.post("/api/v1/logout", json={}, headers=h).status_code == 200
    assert client.get("/api/v1/session").status_code == 401
    token = auth.issue_token("operator")
    response = client.post(
        "/api/v1/tools/updater_job_get",
        json={"job_id": job["job_id"]},
        headers={"Authorization": "Bearer " + token},
    )
    assert response.json()["job_id"] == job["job_id"]
    assert not response.json()["cancel_requested"]
    e.coordinator.run_job(job["job_id"])
    assert e.coordinator.job("operator", job["job_id"])["state"] == "succeeded"


def test_reader_cannot_authorize_and_changed_principal_revokes_session(web):
    client, auth, e = web
    csrf = login(client)
    e.coordinator.authority.provision("operator", ["read"], ["app"])
    assert client.get("/api/v1/session").status_code == 401
    assert (
        client.post(
            "/api/v1/grants", json={}, headers={"Origin": ORIGIN, "X-CSRF-Token": csrf}
        ).status_code
        == 401
    )


def test_login_rate_limit_and_cookie_security(web):
    client, _, _ = web
    bootstrap = client.get("/api/v1/bootstrap").json()
    headers = {"Origin": ORIGIN, "X-CSRF-Token": bootstrap["csrf_token"]}
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/login", json={"username": "operator", "password": "wrong"}, headers=headers
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/login", json={"username": "operator", "password": "wrong"}, headers=headers
        ).status_code
        == 429
    )
    cookie = client.get("/api/v1/bootstrap").headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=strict" in cookie


def mcp_call(client, token, method, params=None, identity=1):
    payload = {"jsonrpc": "2.0", "id": identity, "method": method}
    if params is not None:
        payload["params"] = params
    return client.post(
        "/mcp",
        json=payload,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/json, text/event-stream",
        },
    )


def test_streamable_mcp_auth_catalog_and_strict_runtime_schema(web):
    client, auth, e = web
    unauthorized = client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Accept": "application/json, text/event-stream"},
    )
    assert unauthorized.status_code == 401
    token = auth.issue_token("operator")
    initialized = mcp_call(
        client,
        token,
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    )
    assert initialized.status_code == 200, initialized.text
    result = mcp_call(client, token, "tools/list").json()["result"]["tools"]
    assert {x["name"] for x in result} == set(TOOLS)
    assert (
        next(x for x in result if x["name"] == "updater_update_execute")["inputSchema"][
            "additionalProperties"
        ]
        is False
    )
    bad = mcp_call(
        client,
        token,
        "tools/call",
        {
            "name": "updater_update_plan",
            "arguments": {
                "targets": {"app": e.target_id},
                "request_key": "mcp",
                "command": "private-do-not-echo",
            },
        },
    ).json()["result"]
    assert bad["isError"] and "private-do-not-echo" not in json.dumps(bad)
    valid = mcp_call(
        client,
        token,
        "tools/call",
        {
            "name": "updater_update_plan",
            "arguments": {"targets": {"app": e.target_id}, "request_key": "mcp"},
        },
    ).json()["result"]
    assert not valid["isError"]
    assert valid["structuredContent"]["action"] == "update"


@pytest.mark.parametrize("name", list(TOOLS))
def test_every_adapter_uses_strict_same_input_contract(environment, name):
    with pytest.raises(Exception):
        Facade(environment.coordinator).invoke("operator", name, {"command": "never-accepted"})
