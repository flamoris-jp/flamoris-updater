"""Private GitHub access never forwards credentials to asset storage."""

from types import SimpleNamespace

import httpx
import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_updater_adapters import github_releases as github
from flamoris_updater_adapters.artifacts import Fetcher

BASE = "https://github.com/example/private/releases/download/v1.0/catalog.json"
API = "https://api.github.com/repos/example/private/releases"
CDN = "https://release-assets.githubusercontent.com/file?signature=temporary"


@pytest.fixture(autouse=True)
def credentials(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "existing-github-token")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("FLAMORIS_GITHUB_USER", raising=False)


def fetch(handler):
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
        auth=("ambient", "secret"),
        headers={"Cookie": "ambient", "Host": "wrong"},
    )
    return Fetcher([BASE], client, public_redirects=True, github_releases=True)


@pytest.mark.parametrize("direct", [False, True])
@pytest.mark.parametrize("latest", [False, True])
def test_private_release_uses_exact_api_then_credential_free_storage(direct, latest):
    requests, responses = [], []
    url = BASE if not latest else BASE.replace("download/v1.0", "latest/download")

    def serve(request):
        requests.append(request)
        assert request.headers["host"] == request.url.host
        assert "cookie" not in request.headers
        assert "proxy-authorization" not in request.headers
        if request.url.host == "api.github.com":
            assert request.headers["authorization"] == "Bearer existing-github-token"
        else:
            assert "authorization" not in request.headers
        location = str(request.url)
        if location == url:
            response = httpx.Response(404)
        elif location == API + ("/latest" if latest else "/tags/v1.0"):
            response = httpx.Response(200, json={"id": 9, "tag_name": "v1.0", "draft": False})
        elif location == API + "/9/assets?per_page=100&page=1":
            response = httpx.Response(
                200,
                json=[
                    {
                        "id": 42,
                        "name": "catalog.json",
                        "state": "uploaded",
                        "size": 7,
                        "url": "https://evil.invalid/ignored",
                        "browser_download_url": "https://evil.invalid/ignored",
                    }
                ],
            )
        elif location == API + "/assets/42":
            assert request.headers["accept"] == "application/octet-stream"
            response = (
                httpx.Response(200, content=b"payload")
                if direct
                else httpx.Response(302, headers={"Location": CDN})
            )
        else:
            assert location == CDN
            response = httpx.Response(200, content=b"payload")
        responses.append(response)
        return response

    assert fetch(serve).bytes(url, 7) == b"payload"
    assert len(requests) == (4 if direct else 5)
    assert all(response.is_closed for response in responses)


@pytest.mark.parametrize("status", [200, 403, 500])
def test_public_or_failed_requests_never_consult_credentials(monkeypatch, status):
    monkeypatch.setattr(github, "credential", lambda: pytest.fail("Unnecessary credential read"))
    reader = fetch(lambda request: httpx.Response(status, content=b"public"))
    if status == 200:
        assert reader.bytes(BASE, 6) == b"public"
    else:
        with pytest.raises(UpdateError):
            reader.bytes(BASE, 6)


@pytest.mark.parametrize(
    "target",
    [
        "https://evil.invalid/file",
        "http://release-assets.githubusercontent.com/file",
        "https://release-assets.githubusercontent.com:444/file",
        API + "/assets/43",
        CDN + "#fragment",
        "https://user:secret@release-assets.githubusercontent.com/file",
    ],
)
def test_private_api_asset_redirect_rejection_never_contacts_target(target):
    requests = []

    def serve(request):
        requests.append(str(request.url))
        if request.url.host == "github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/tags/v1.0"):
            return httpx.Response(200, json={"id": 9, "tag_name": "v1.0"})
        if request.url.path.endswith("/9/assets"):
            return httpx.Response(
                200, json=[{"id": 42, "name": "catalog.json", "state": "uploaded", "size": 7}]
            )
        return httpx.Response(302, headers={"Location": target})

    with pytest.raises(UpdateError):
        fetch(serve).bytes(BASE, 7)
    assert requests[-1] == API + "/assets/42"
    assert len(requests) == 4


def test_api_metadata_redirect_is_not_followed():
    requests = []

    def serve(request):
        requests.append(str(request.url))
        return (
            httpx.Response(404)
            if len(requests) == 1
            else httpx.Response(302, headers={"Location": API + "/other"})
        )

    with pytest.raises(UpdateError):
        fetch(serve).bytes(BASE, 7)
    assert len(requests) == 2


@pytest.mark.parametrize("pages", [2, 10])
def test_asset_pagination_is_bounded(pages):
    requests = []

    def serve(request):
        requests.append(str(request.url))
        if request.url.host == "github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/tags/v1.0"):
            return httpx.Response(200, json={"id": 9, "tag_name": "v1.0"})
        if request.url.path.endswith("/9/assets"):
            page = int(request.url.params["page"])
            if pages == 2 and page == 2:
                return httpx.Response(
                    200, json=[{"id": 42, "name": "catalog.json", "state": "uploaded", "size": 7}]
                )
            return httpx.Response(200, json=[{"name": "other"} for _ in range(100)])
        return httpx.Response(200, content=b"payload")

    if pages == 2:
        assert fetch(serve).bytes(BASE, 7) == b"payload"
        assert len(requests) == 5
    else:
        with pytest.raises(UpdateError):
            fetch(serve).bytes(BASE, 7)
        assert len(requests) == 12


@pytest.mark.parametrize("failure", ["timeout", "missing", "invalid_output", "unauthorized"])
def test_gh_failure_never_exposes_output(monkeypatch, failure):
    monkeypatch.delenv("GH_TOKEN")

    def execute(*args, **kwargs):
        if failure == "timeout":
            raise github.subprocess.TimeoutExpired(args[0], 15, output=b"private")
        if failure == "missing":
            raise FileNotFoundError("private")
        return SimpleNamespace(
            returncode=1 if failure == "unauthorized" else 0, stdout=b"\xffprivate"
        )

    monkeypatch.setattr(github.subprocess, "run", execute)
    assert github.credential() is None


def test_missing_credentials_has_actionable_sanitized_error(monkeypatch):
    monkeypatch.setattr(github, "credential", lambda: None)
    with pytest.raises(UpdateError) as error:
        fetch(lambda request: httpx.Response(404)).bytes(BASE, 7)
    assert error.value.code == "github_access_required"
    assert "existing-github-token" not in str(error.value)


@pytest.mark.parametrize(
    "fault", ["wrong_tag", "draft", "missing", "large", "invalid_json", "bad_id"]
)
def test_invalid_metadata_stops_before_payload(fault):
    paths = []

    def serve(request):
        paths.append(request.url.path)
        if request.url.host == "github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/tags/v1.0"):
            if fault == "invalid_json":
                return httpx.Response(200, content=b"invalid")
            return httpx.Response(
                200,
                json={
                    "id": True if fault == "bad_id" else 9,
                    "tag_name": "other" if fault == "wrong_tag" else "v1.0",
                    "draft": fault == "draft",
                },
            )
        return httpx.Response(
            200,
            json=[]
            if fault == "missing"
            else [
                {
                    "id": 42,
                    "name": "catalog.json",
                    "state": "uploaded",
                    "size": 8,
                }
            ],
        )

    with pytest.raises(UpdateError):
        fetch(serve).bytes(BASE, 7)
    assert not any(path.endswith("/assets/42") for path in paths)


@pytest.mark.parametrize("raw", [b"oversized", b"payload"])
def test_private_payload_streaming_budget(raw):
    def serve(request):
        if request.url.host == "github.com":
            return httpx.Response(404)
        if request.url.path.endswith("/tags/v1.0"):
            return httpx.Response(200, json={"id": 9, "tag_name": "v1.0"})
        if request.url.path.endswith("/9/assets"):
            return httpx.Response(
                200, json=[{"id": 42, "name": "catalog.json", "state": "uploaded", "size": 7}]
            )
        return httpx.Response(200, content=raw)

    if len(raw) > 7:
        with pytest.raises(UpdateError) as error:
            fetch(serve).bytes(BASE, 7)
        assert error.value.code == "quota_exceeded"
    else:
        assert fetch(serve).bytes(BASE, 7) == raw


def test_credential_reads_existing_gh_as_selected_normal_user(monkeypatch):
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.setenv("FLAMORIS_GITHUB_USER", "operator")
    monkeypatch.setattr(
        github.pwd, "getpwnam", lambda name: SimpleNamespace(pw_uid=1000, pw_dir="/home/operator")
    )
    monkeypatch.setattr(github.os, "geteuid", lambda: 0)

    def execute(command, **options):
        assert command == [
            "/usr/sbin/runuser",
            "--user",
            "operator",
            "--",
            "/usr/bin/gh",
            "auth",
            "token",
            "--hostname",
            "github.com",
        ]
        assert options["env"] == {"PATH": "/usr/bin:/bin", "HOME": "/home/operator"}
        assert options["cwd"] == "/" and options["timeout"] == 15
        return SimpleNamespace(returncode=0, stdout=b"existing-token\n")

    monkeypatch.setattr(github.subprocess, "run", execute)
    assert github.credential() == "existing-token"


def test_environment_credential_precedence_and_invalid_value(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "second")
    monkeypatch.setattr(github.subprocess, "run", lambda *a, **k: pytest.fail("No gh needed"))
    assert github.credential() == "existing-github-token"
    monkeypatch.setenv("GH_TOKEN", "token\nheader")
    assert github.credential() is None


@pytest.mark.parametrize(
    "url",
    [
        BASE.replace("github.com", "github.com.evil.invalid"),
        BASE + "?token=secret",
        BASE.replace("catalog.json", "%2Fother"),
        BASE.replace("catalog.json", "%2e%2e"),
        BASE.replace("v1.0", "%2e%2e%2Ftag"),
    ],
)
def test_unsupported_location_never_reads_credentials(monkeypatch, url):
    monkeypatch.setattr(github, "credential", lambda: pytest.fail("Must validate location first"))
    with pytest.raises(UpdateError):
        list(github.private_chunks(None, url, 7))
