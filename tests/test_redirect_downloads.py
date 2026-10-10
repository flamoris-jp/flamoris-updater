"""Public release redirects preserve destination, credential and byte limits."""

import httpx
import pytest

from flamoris_update_core.errors import UpdateError
from flamoris_updater_adapters.artifacts import Fetcher

ASSET = "https://github.com/example/application/releases/download/v1.0.0/image.tar"
CDN = "https://release-assets.githubusercontent.com/github-production-release-asset/1/image"


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_github_release_redirect_downloads_without_ambient_credentials(status):
    requests, responses = [], []

    def serve(request):
        requests.append(request)
        assert request.method == "GET"
        assert "authorization" not in request.headers
        assert "proxy-authorization" not in request.headers
        assert "cookie" not in request.headers
        assert request.headers["host"] == request.url.host
        response = (
            httpx.Response(status, headers={"Location": CDN + "?signature=temporary"})
            if len(requests) == 1
            else httpx.Response(200, content=b"payload")
        )
        responses.append(response)
        return response

    client = httpx.Client(
        transport=httpx.MockTransport(serve),
        follow_redirects=True,
        auth=("private-user", "private-password"),
        headers={
            "Authorization": "Bearer private",
            "Proxy-Authorization": "private",
            "Host": "wrong",
        },
        cookies={"private_session": "private"},
    )
    fetcher = Fetcher(["https://github.com"], client, public_redirects=True)
    assert fetcher.bytes(ASSET, 7) == b"payload"
    assert [str(r.url) for r in requests] == [ASSET, CDN + "?signature=temporary"]
    assert all(r.is_closed for r in responses)


def test_relative_same_origin_redirects_and_latest_github_release():
    paths = []

    def serve(request):
        paths.append(request.url.path)
        if request.url.path.endswith("/latest/download/catalog.json"):
            return httpx.Response(
                302, headers={"Location": "/example/application/releases/download/v1/catalog.json"}
            )
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": CDN})
        return httpx.Response(200, content=b"catalog")

    fetcher = Fetcher(
        ["https://github.com"],
        httpx.Client(transport=httpx.MockTransport(serve)),
        public_redirects=True,
    )
    assert (
        fetcher.bytes(
            "https://github.com/example/application/releases/latest/download/catalog.json", 7
        )
        == b"catalog"
    )
    assert len(paths) == 3

    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(302, headers={"Location": "final"})
                if request.url.path.endswith("/start")
                else httpx.Response(200, content=b"same")
            )
        )
    )
    assert (
        Fetcher(["https://example.invalid"], client, public_redirects=True).bytes(
            "https://example.invalid/start", 4
        )
        == b"same"
    )


@pytest.mark.parametrize(
    "target",
    [
        "http://release-assets.githubusercontent.com/file",
        "https://evil.example.invalid/file",
        "https://release-assets.githubusercontent.com.evil.invalid/file",
        "https://evil.release-assets.githubusercontent.com/file",
        "https://release-assets.githubusercontent.com:444/file",
        "https://user:secret@release-assets.githubusercontent.com/file",
        CDN + "#fragment",
        "/%2e%2e/escape",
        "https://release-assets.githubusercontent.com\\@evil.invalid/file",
        "",
        " " + CDN,
    ],
)
def test_rejected_redirect_target_is_never_contacted_even_with_auto_follow_client(target):
    requests, responses = [], []

    def serve(request):
        requests.append(str(request.url))
        response = httpx.Response(302, headers={"Location": target})
        responses.append(response)
        return response

    client = httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=True)
    with pytest.raises(UpdateError):
        Fetcher(["https://github.com"], client, public_redirects=True).bytes(ASSET, 10)
    assert requests == [ASSET]
    assert all(r.is_closed for r in responses)


@pytest.mark.parametrize(
    "initial",
    [
        "https://example.invalid/catalog.json",
        "https://github.com/example/application/issues/1",
        "https://github.com.evil.invalid/example/application/releases/download/v1/file",
        "https://api.github.com/repos/example/application/releases/assets/1",
    ],
)
def test_cdn_exception_requires_an_initial_github_release_url(initial):
    requests = []

    def serve(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": CDN})

    with pytest.raises(UpdateError):
        Fetcher(
            [initial], httpx.Client(transport=httpx.MockTransport(serve)), public_redirects=True
        ).bytes(initial, 10)
    assert requests == [initial]


def test_redirect_chain_stays_confined_after_entering_cdn():
    requests = []

    def serve(request):
        requests.append(str(request.url))
        return httpx.Response(
            302, headers={"Location": CDN if len(requests) == 1 else "https://evil.invalid/file"}
        )

    with pytest.raises(UpdateError):
        Fetcher(
            [ASSET], httpx.Client(transport=httpx.MockTransport(serve)), public_redirects=True
        ).bytes(ASSET, 10)
    assert requests == [ASSET, CDN]


def test_redirect_loop_has_a_fixed_request_bound_and_closed_responses():
    responses = []

    def serve(request):
        response = httpx.Response(302, headers={"Location": ASSET})
        responses.append(response)
        return response

    with pytest.raises(UpdateError):
        Fetcher(
            [ASSET], httpx.Client(transport=httpx.MockTransport(serve)), public_redirects=True
        ).bytes(ASSET, 10)
    assert len(responses) == 6
    assert all(r.is_closed for r in responses)


@pytest.mark.parametrize("headers", [{}, {"Content-Length": "11"}, {"Content-Length": "invalid"}])
def test_redirect_does_not_remove_final_response_byte_budget(headers):
    def serve(request):
        return (
            httpx.Response(302, headers={"Location": CDN})
            if request.url.host == "github.com"
            else httpx.Response(200, headers=headers, content=b"elevenbytes")
        )

    with pytest.raises(UpdateError) as error:
        Fetcher(
            [ASSET], httpx.Client(transport=httpx.MockTransport(serve)), public_redirects=True
        ).bytes(ASSET, 10)
    assert error.value.code == "quota_exceeded"


def test_strict_fetcher_still_rejects_same_origin_redirect_and_preserves_initial_auth():
    requests = []

    def serve(request):
        requests.append(request)
        return httpx.Response(302, headers={"Location": "/next"})

    client = httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=True)
    with pytest.raises(UpdateError):
        Fetcher([ASSET], client).bytes(ASSET, 10, headers={"Authorization": "Bearer registry"})
    assert len(requests) == 1
    assert requests[0].headers["Authorization"] == "Bearer registry"


def test_transport_failure_does_not_expose_temporary_query_or_credentials():
    def serve(request):
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": CDN + "?secret=temporary"})
        raise httpx.ConnectError("secret=temporary", request=request)

    with pytest.raises(UpdateError) as error:
        Fetcher(
            [ASSET], httpx.Client(transport=httpx.MockTransport(serve)), public_redirects=True
        ).bytes(ASSET, 10)
    assert "temporary" not in str(error.value)


@pytest.mark.parametrize(
    "url", [ASSET + "\n", " https://github.com/file", "https://github.com:invalid/file"]
)
def test_invalid_initial_url_is_rejected_before_network(url):
    requests = []
    with pytest.raises(UpdateError):
        Fetcher(
            ["https://github.com"],
            httpx.Client(transport=httpx.MockTransport(lambda r: requests.append(r))),
            public_redirects=True,
        ).bytes(url, 10)
    assert not requests
