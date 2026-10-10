"""Persistent credentials exercise the real Web/session and MCP adapters."""

import pytest
from test_interfaces import ORIGIN, login, mcp_call
from test_interfaces import web as base_web

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import dumps
from flamoris_updater_adapters.auth import AuthStore


@pytest.fixture
def web(environment):
    yield from base_web.__wrapped__(environment)


def test_key_survives_expiry_and_auth_restart_but_rotation_and_revocation_work(web):
    client, auth, e = web
    headers = {"Origin": ORIGIN, "X-CSRF-Token": login(client)}
    result = client.post("/api/v1/integrations", json={"label": "automation"}, headers=headers)
    assert result.status_code == 200, result.text
    key = result.json()
    short = auth.issue_token("operator")
    # The clock is shared with authority; advance past the ordinary token lifetime.
    auth.clock = lambda: e.clock() + 31 * 86400
    restarted = AuthStore(auth.journal, auth.authority, auth.clock)
    assert restarted.bearer(key["token"]) == key["integration_id"]
    with pytest.raises(UpdateError):
        restarted.bearer(short)
    assert mcp_call(client, key["token"], "tools/list", {}).status_code == 200
    public = dumps(auth.integrations("operator"))
    auth.journal.flush_export()
    assert key["token"].encode() not in public
    assert key["token"].encode() not in (auth.journal.directory / "recovery.jsonl").read_bytes()
    rotated = auth.integration("operator", "new label", identity=key["integration_id"])
    assert restarted.bearer(rotated["token"]) == key["integration_id"]
    assert mcp_call(client, key["token"], "tools/list", {}).status_code == 401
    auth.revoke_integration("operator", key["integration_id"])
    assert mcp_call(client, rotated["token"], "tools/list", {}).status_code == 401


def test_credentials_cannot_mint_other_keys_and_owner_changes_invalidate_them(web):
    client, auth, e = web
    headers = {"Origin": ORIGIN, "X-CSRF-Token": login(client)}
    assert client.post("/api/v1/integrations", json={"label": "missing csrf"}).status_code == 403
    issued = client.post(
        "/api/v1/integrations", json={"label": "read only", "execute": False}, headers=headers
    ).json()
    secret = issued["token"]
    bearer = {"Authorization": "Bearer " + secret}
    for route in [
        "/api/v1/integrations",
        "/api/v1/integrations/" + issued["integration_id"] + "/rotate",
    ]:
        assert client.post(route, json={"label": "escalate"}, headers=bearer).status_code == 403
    assert client.get("/api/v1/integrations", headers=bearer).status_code == 403
    subject = auth.bearer(secret)
    with pytest.raises(UpdateError):
        auth.authority.require(subject, "execute", ["app"])
    with pytest.raises(UpdateError):
        auth.authority.require(subject, "operator", [])
    auth.authority.provision("operator", ["read", "execute", "operator"], ["app"])
    assert mcp_call(client, secret, "tools/list", {}).status_code == 401
    second = auth.integration("operator", "second")
    auth.disable_user("operator")
    assert mcp_call(client, second["token"], "tools/list", {}).status_code == 401


def test_other_operator_cannot_rotate_or_revoke_owned_key(web):
    _, auth, _ = web
    key = auth.integration("operator", "owned")
    auth.authority.provision("other", ["read", "execute", "operator"], ["app"])
    with pytest.raises(UpdateError):
        auth.integration("other", "stolen", identity=key["integration_id"])
    with pytest.raises(UpdateError):
        auth.revoke_integration("other", key["integration_id"])
    assert auth.integrations("other")["items"] == []
