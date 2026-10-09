import errno
import os
import socket
import struct
import threading
from contextlib import contextmanager
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient
from test_application_owner import configured, request

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.local_transport import UnixClient, receive_exact
from flamoris_update_core.owner_cli import ServerConfiguration, create_server, serve_connection
from flamoris_update_core.wire import loads
from flamoris_updater_adapters.backends import LocalOwner
from flamoris_updater_adapters.cli import main
from flamoris_updater_adapters.config import Endpoint, HostAPIConfig, OwnerConnection, ReleaseSource
from flamoris_updater_adapters.helper import Dispatch
from flamoris_updater_adapters.host_api import create_host_app


@contextmanager
def local_owner(tmp_path, allowed=True, guard=lambda: None):
    owner, target, _, _ = configured(tmp_path)
    cfg = ServerConfiguration(
        owner=owner.config,
        socket_path=str(tmp_path / "owner.sock"),
        socket_group_id=os.getegid(),
        allowed_peer_uids=[os.geteuid()] if allowed else [os.geteuid() + 1],
    )
    try:
        server = create_server(owner, cfg, guard)
    except PermissionError as error:
        if error.errno != errno.EPERM:
            raise
        pytest.skip("Named Unix listeners are unavailable in this environment; CI runs them")
    with server:
        thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.01})
        thread.start()
        try:
            client = UnixClient(cfg.socket_path, expected_uid=os.geteuid())
            yield owner, target, LocalOwner(client), client
        finally:
            server.shutdown()
            thread.join(timeout=2)
            assert not thread.is_alive()
    assert not (tmp_path / "owner.sock").exists()


def test_real_owner_inspection_and_operation_need_no_certificates(tmp_path):
    with local_owner(tmp_path) as (owner, target, remote, _):
        assert remote.inspect(owner.profile).application_id == owner.profile.application_id
        assert remote.perform(request(owner, target, "prepare")).outcome == "verified"
        assert (tmp_path / "owner.sock").stat().st_mode & 0o777 == 0o660


def test_owner_denies_wrong_os_peer_before_effects(tmp_path):
    with local_owner(tmp_path, allowed=False) as (owner, target, remote, _):
        with pytest.raises(UpdateError) as error:
            remote.perform(request(owner, target, "prepare"))
        assert error.value.code == "forbidden"
        assert owner.journal.get("owner_operation", "update-job.prepare") is None


def test_client_checks_server_uid_before_sending_operation(tmp_path):
    with local_owner(tmp_path) as (owner, target, _, client):
        client.expected_uid = os.geteuid() + 1
        with pytest.raises(UpdateError) as error:
            LocalOwner(client).perform(request(owner, target, "prepare"))
        assert error.value.code == "forbidden"
        assert owner.journal.get("owner_operation", "update-job.prepare") is None


def test_owner_checks_config_guard_and_bounds_frames(tmp_path):
    def changed():
        raise UpdateError("policy_changed")

    with local_owner(tmp_path, guard=changed) as (_, _, _, client):
        with pytest.raises(UpdateError) as error:
            client.call({"action": "/inspect", "body": {}})
        assert error.value.code == "policy_changed"
    second = tmp_path / "second"
    second.mkdir(mode=0o700)
    with local_owner(second) as (_, _, _, client):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
            connection.settimeout(2)
            connection.connect(client.path)
            connection.sendall(struct.pack("!I", 1024 * 1024 + 1))
            size = struct.unpack("!I", receive_exact(connection, 4))[0]
            assert loads(receive_exact(connection, size))["error"] == "quota_exceeded"
        with pytest.raises(UpdateError):
            client.call({"action": "/arbitrary-shell", "body": {}})


def test_owner_refuses_writable_directory_and_existing_socket(tmp_path):
    owner, _, _, _ = configured(tmp_path)
    cfg = SimpleNamespace(socket_path=str(tmp_path / "owner.sock"), socket_group_id=os.getegid())
    tmp_path.chmod(0o777)
    with pytest.raises(UpdateError):
        create_server(owner, cfg, lambda: None)
    tmp_path.chmod(0o700)
    try:
        server = create_server(owner, cfg, lambda: None)
    except PermissionError as error:
        if error.errno != errno.EPERM:
            raise
        pytest.skip("Named Unix listeners are unavailable in this environment; CI runs them")
    with server:
        with pytest.raises(UpdateError):
            create_server(owner, cfg, lambda: None)


@pytest.mark.parametrize(
    "url", ["https://updater.example.invalid", "http://127.0.0.1:8765", "http://[::1]:8765"]
)
def test_api_accepts_normal_https_or_loopback_without_client_identity(url):
    assert Endpoint(url=url).url == url


@pytest.mark.parametrize(
    "url",
    [
        "http://192.0.2.1",
        "http://localhost",
        "http://0.0.0.0",
        "http://127.0.0.1@evil.invalid",
        "https://updater.invalid?token=secret",
    ],
)
def test_api_rejects_plaintext_remote_or_ambiguous_origin(url):
    with pytest.raises((UpdateError, ValidationError)):
        Endpoint(url=url)


def test_host_loopback_http_still_rejects_unsigned_operations(environment):
    dispatch = Dispatch(environment.host)
    app = create_host_app(SimpleNamespace(call=dispatch.invoke))
    with TestClient(app) as client:
        unsigned = client.post("/api/v1/operations/run", json={"command": "inspect"})
        assert unsigned.status_code == 403
        assert environment.backend.calls == []
        packet = environment.signer.packet(
            dict(
                command="inspect",
                domain="example-domain",
                host_id="host",
                epoch=1,
                deployment_id="app",
            )
        )
        assert client.post("/api/v1/deployments/inspect", json=packet).status_code == 200


def test_old_certificate_settings_are_rejected_and_host_is_loopback_only():
    host = dict(
        config_version=1,
        socket_path="/run/updater/helper.sock",
        helper_timeout_seconds=120,
        listen_host="127.0.0.1",
        listen_port=8765,
    )
    assert HostAPIConfig(**host)
    with pytest.raises(ValidationError):
        HostAPIConfig(**{**host, "listen_host": "0.0.0.0"})
    with pytest.raises(ValidationError):
        HostAPIConfig(
            **{**host, "server_tls": {"ca_file": "/ca", "cert_file": "/cert", "key_file": "/key"}}
        )
    with pytest.raises(ValidationError):
        Endpoint(
            url="https://updater.invalid",
            tls={"ca_file": "/ca", "cert_file": "/cert", "key_file": "/key"},
        )
    assert OwnerConnection(socket_path="/run/app/owner.sock", expected_uid=1000)
    assert ReleaseSource(
        application_id="app",
        catalog_url="https://releases.invalid/catalog",
        catalog_signature_url="https://releases.invalid/catalog.sig",
        origins=["https://releases.invalid"],
    )


def test_cli_calls_with_only_url_and_private_bearer_token(tmp_path, monkeypatch, capsys):
    token = tmp_path / "token"
    token.write_text("test-private-token\n")
    token.chmod(0o600)
    arguments = tmp_path / "arguments.json"
    arguments.write_text('{"job_id":"example-job"}')
    requests = []

    def respond(req):
        requests.append(req)
        return httpx.Response(200, json={"job_id": "example-job"})

    monkeypatch.setattr(
        Endpoint, "client", lambda _: httpx.Client(transport=httpx.MockTransport(respond))
    )
    main(
        [
            "call",
            "--url",
            "https://updater.example.invalid",
            "--token-file",
            str(token),
            "--tool",
            "updater_job_get",
            "--arguments",
            str(arguments),
        ]
    )
    assert requests[0].headers["authorization"] == "Bearer test-private-token"
    assert "example-job" in capsys.readouterr().out


@pytest.mark.parametrize("allowed", [True, False])
def test_owner_os_peer_and_real_operation_over_socketpair(tmp_path, allowed):
    owner, target, _, _ = configured(tmp_path)
    server, client = socket.socketpair()
    calls = []
    thread = threading.Thread(
        target=serve_connection,
        args=(
            server,
            owner,
            [os.geteuid()] if allowed else [os.geteuid() + 1],
            lambda: calls.append("guard"),
        ),
    )
    thread.start()
    try:
        from flamoris_update_core.wire import dumps

        body = dumps(
            {"action": "/operations", "body": request(owner, target, "prepare").model_dump()}
        )
        client.sendall(struct.pack("!I", len(body)) + body)
        length = struct.unpack("!I", receive_exact(client, 4))[0]
        result = loads(receive_exact(client, length))
        if allowed:
            assert result["outcome"] == "verified"
            assert calls == ["guard"]
        else:
            assert result["error"] == "forbidden"
            assert calls == []
            assert owner.journal.get("owner_operation", "update-job.prepare") is None
    finally:
        thread.join(timeout=2)
        server.close()
        client.close()
        assert not thread.is_alive()


def test_owner_rejects_oversized_frames_without_reading_body(tmp_path):
    owner, _, _, _ = configured(tmp_path)
    server, client = socket.socketpair()
    thread = threading.Thread(
        target=serve_connection, args=(server, owner, [os.geteuid()], lambda: None)
    )
    thread.start()
    try:
        client.sendall(struct.pack("!I", 1024 * 1024 + 1))
        size = struct.unpack("!I", receive_exact(client, 4))[0]
        assert loads(receive_exact(client, size))["error"] == "quota_exceeded"
    finally:
        thread.join(timeout=2)
        server.close()
        client.close()
        assert not thread.is_alive()


def test_uninstalled_owner_inspection_round_trip_keeps_required_null_fields(tmp_path):
    from flamoris_update_core.inventory import Observation
    from flamoris_update_core.owner_cli import dispatch
    from flamoris_update_core.wire import decode, digest, dumps

    owner, _, _, _ = configured(tmp_path)
    raw = dispatch(
        owner,
        "/inspect",
        dumps(
            dict(
                contract_version=1,
                observation_id="obs-initial",
                deployment_id=owner.profile.id,
                resource_ids=sorted(owner.profile.resources.values()),
                profile_digest=digest(dumps(owner.profile)),
            )
        ),
    )
    result = decode(Observation, raw)
    assert result.manifest_digest is None
    assert result.release is None


def test_cli_loopback_connection_keeps_public_origin_boundary(
    environment, tmp_path, monkeypatch, capsys
):
    from flamoris_updater_adapters.auth import AuthStore
    from flamoris_updater_adapters.web import create_app

    e = environment
    public = "https://updater.example.invalid"
    auth = AuthStore(e.coordinator.journal, e.coordinator.authority, e.clock)
    auth.user("operator", "isolated-test-password", ["read"], ["app"])
    token = tmp_path / "token"
    token.write_text(auth.issue_token("operator"))
    token.chmod(0o600)
    arguments = tmp_path / "arguments.json"
    arguments.write_text("{}")
    app = create_app(e.coordinator, auth, public, run_worker=False)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        monkeypatch.setattr(Endpoint, "client", lambda _: client)
        main(
            [
                "call",
                "--url",
                "http://127.0.0.1:8765",
                "--public-origin",
                public,
                "--token-file",
                str(token),
                "--tool",
                "updater_inventory_list",
                "--arguments",
                str(arguments),
            ]
        )
    assert loads(capsys.readouterr().out.encode()) == {"items": [], "next_cursor": None}
