import re

import httpx
import pytest
from starlette.testclient import TestClient
from test_interfaces import ORIGIN, mcp_call

from flamoris_updater_adapters.auth import AuthStore
from flamoris_updater_adapters.cli import main
from flamoris_updater_adapters.config import Endpoint
from flamoris_updater_adapters.web import create_app
from flamoris_updater_adapters.webpaths import base_path


@pytest.mark.parametrize("prefix", ["", "/updater", "/tools/updater"])
def test_browser_assets_login_csrf_bearer_and_mcp_share_public_prefix(environment, prefix):
    e = environment
    auth = AuthStore(e.coordinator.journal, e.coordinator.authority, e.clock)
    auth.user("operator", "isolated-test-password", ["read", "operator"], ["app"])
    app = create_app(e.coordinator, auth, ORIGIN, run_worker=False, base_path=prefix)
    with TestClient(app, base_url=ORIGIN) as client:
        if prefix:
            canonical = client.get(prefix, follow_redirects=False)
            assert canonical.status_code == 308
            assert canonical.headers["location"] == prefix + "/"
            for outside in ["/", "/api/v1/session", "/mcp", prefix + "-other/health"]:
                assert client.get(outside).status_code == 404
        html = client.get(prefix + "/").text
        assert "__UPDATER_BASE_PATH__" not in html
        assert f'name="updater-base-path" content="{prefix}"' in html
        for asset in re.findall(r'(?:src|href)="([^"]*/static/[^"]+)"', html):
            assert asset.startswith(prefix + "/static/")
            assert client.get(asset).status_code == 200
        assert client.get(prefix + "/health").status_code == 200
        init = client.get(prefix + "/api/v1/bootstrap")
        assert "Path=/" in init.headers["set-cookie"] and "Secure" in init.headers["set-cookie"]
        login = client.post(
            prefix + "/api/v1/login",
            json={"username": "operator", "password": "isolated-test-password"},
            headers={"Origin": ORIGIN, "X-CSRF-Token": init.json()["csrf_token"]},
        )
        assert login.status_code == 200
        assert client.get(prefix + "/api/v1/session").json()["subject"] == "operator"
        assert (
            client.post(
                prefix + "/api/v1/logout",
                json={},
                headers={"Origin": ORIGIN + "/updater", "X-CSRF-Token": login.json()["csrf_token"]},
            ).status_code
            == 403
        )
        assert client.get(prefix + "/health", headers={"Host": "evil.invalid"}).status_code == 403
        assert (
            client.post(
                prefix + "/api/v1/logout",
                json={},
                headers={"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]},
            ).status_code
            == 200
        )
        token = auth.issue_token("operator")
        assert mcp_call(client, token, "tools/list", path=prefix + "/mcp").status_code == 200
        assert (
            client.post(
                prefix + "/mcp", json={}, headers={"Accept": "application/json, text/event-stream"}
            ).status_code
            == 401
        )
        assert mcp_call(
            client,
            token,
            "tools/call",
            {"name": "updater_inventory_list", "arguments": {}},
            path=prefix + "/mcp",
        ).json()["result"]["structuredContent"] == {"items": [], "next_cursor": None}


@pytest.mark.parametrize(
    "value",
    [
        "/",
        "/updater/",
        "//updater",
        "/../updater",
        "/updater%2fapi",
        "/updater?token=x",
        '/x"',
        "/é",
        "/" + "x" * 257,
    ],
)
def test_ambiguous_or_injectable_prefix_is_rejected(value):
    with pytest.raises(ValueError):
        base_path(value)


@pytest.mark.parametrize(
    "url",
    [
        "https://updater.example.invalid/updater",
        "http://127.0.0.1:8764/updater/",
        "http://[::1]:8764/tools/updater",
    ],
)
def test_cli_posts_to_prefixed_url_with_public_host(tmp_path, monkeypatch, capsys, url):
    token = tmp_path / "token"
    token.write_text("isolated-private-token")
    token.chmod(0o600)
    arguments = tmp_path / "arguments"
    arguments.write_text("{}")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"items": []})

    monkeypatch.setattr(
        Endpoint, "client", lambda _: httpx.Client(transport=httpx.MockTransport(respond))
    )
    main(
        [
            "call",
            "--url",
            url,
            "--public-origin",
            ORIGIN,
            "--token-file",
            str(token),
            "--tool",
            "updater_inventory_list",
            "--arguments",
            str(arguments),
        ]
    )
    assert calls[0].url.path.endswith("/updater/api/v1/tools/updater_inventory_list")
    assert calls[0].headers["host"] == "updater.example.invalid"
    assert calls[0].headers["authorization"] == "Bearer isolated-private-token"
    assert "items" in capsys.readouterr().out
