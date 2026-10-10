import re

import httpx
import pytest
from starlette.testclient import TestClient
from test_interfaces import ORIGIN, fake_coordinator, mcp_call

from flamoris_updater_adapters.cli import main
from flamoris_updater_adapters.config import Endpoint
from flamoris_updater_adapters.web import create_app
from flamoris_updater_adapters.webpaths import base_path


@pytest.mark.parametrize("prefix", ["", "/updater", "/tools/updater"])
def test_browser_assets_api_and_mcp_share_public_prefix(tmp_path, prefix):
    app = create_app(fake_coordinator(tmp_path), ORIGIN, run_worker=False, base_path=prefix)
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
        assert client.post(prefix + "/api/v1/tools/updater_apps_list", json={}).status_code == 200
        assert mcp_call(client, "", "tools/list", path=prefix + "/mcp").status_code == 200
        assert client.get(prefix + "/health", headers={"Host": "evil.invalid"}).status_code == 403


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
            "--tool",
            "updater_apps_list",
            "--arguments",
            str(arguments),
        ]
    )
    assert calls[0].url.path.endswith("/updater/api/v1/tools/updater_apps_list")
    assert calls[0].headers["host"] == "updater.example.invalid"
    assert "authorization" not in calls[0].headers
    assert "items" in capsys.readouterr().out
