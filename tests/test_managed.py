"""Real settings/journal/Web/MCP plus controlled Docker/systemd effects.

Root filesystem checks run in the dedicated CI job. No deployed applications,
system units, shared databases or external runtimes are touched by these tests.
"""

import copy
import io
import json
import os
import socket
import struct
import subprocess
import sys
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.testclient import TestClient
from test_interfaces import mcp_call

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.owner_cli import serve_connection
from flamoris_update_core.wire import digest, dumps, loads
from flamoris_updater_adapters.install import Installer
from flamoris_updater_adapters.managed import Catalog, Manager, Start
from flamoris_updater_adapters.recipes import build_recipe
from flamoris_updater_adapters.setup import BootstrapConfig, LocalCoordinator, bootstrap, dispatch
from flamoris_updater_adapters.web import create_app

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0, reason="Protected administrator filesystem flow runs in root CI"
)


@pytest.mark.parametrize("tampered", [False, True])
def test_private_repository_catalog_and_payload_share_managed_digest_checks(
    tmp_path, monkeypatch, tampered
):
    base = "https://github.com/example/private/releases/download/v1.0"
    monkeypatch.setenv("GH_TOKEN", "existing-github-token")
    candidate = recipe()
    candidate["downloads"]["image.tar"]["url"] = base + "/image.tar"
    catalog = Catalog.model_validate({"catalog_version": 1, "recipes": [candidate]})
    payloads = {1: dumps(catalog), 2: b"tampered" if tampered else b"image"}

    def serve(request):
        if request.url.host == "github.com":
            assert "authorization" not in request.headers
            return httpx.Response(404)
        assert request.url.host == "api.github.com"
        assert request.headers["authorization"] == "Bearer existing-github-token"
        if request.url.path.endswith("/tags/v1.0"):
            return httpx.Response(200, json={"id": 9, "tag_name": "v1.0"})
        if request.url.path.endswith("/9/assets"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": asset_id,
                        "name": name,
                        "state": "uploaded",
                        "size": len(payloads[asset_id]),
                    }
                    for asset_id, name in [(1, "catalog.json"), (2, "image.tar")]
                ],
            )
        return httpx.Response(200, content=payloads[int(request.url.path.rsplit("/", 1)[-1])])

    manager = Manager(
        tmp_path / "state",
        tmp_path / "apps",
        client=httpx.Client(transport=httpx.MockTransport(serve)),
    )
    manager.configure(base + "/catalog.json")
    assert manager.catalog(refresh=True) == catalog
    item = catalog.recipes[0].downloads["image.tar"]
    destination = tmp_path / "image.tar"
    if tampered:
        with pytest.raises(UpdateError) as error:
            manager._download(item.url, 1024, destination, item.digest)
        assert error.value.code == "artifact_mismatch"
    else:
        manager._download(item.url, 1024, destination, item.digest)
        assert destination.read_bytes() == b"image"
    assert "existing-github-token" not in dumps(manager.catalog()).decode()


@pytest.mark.parametrize("tampered", [False, True])
def test_github_catalog_and_app_payload_follow_checked_redirects(tmp_path, tampered):
    base = "https://github.com/example/apps/releases/download/initial"
    cdn = "https://release-assets.githubusercontent.com/github-production-release-asset/1/"
    candidate = recipe()
    candidate["downloads"]["image.tar"]["url"] = base + "/image.tar"
    catalog = Catalog.model_validate({"catalog_version": 1, "recipes": [candidate]})
    requests = []

    def serve(request):
        requests.append(str(request.url))
        filename = request.url.path.rsplit("/", 1)[-1]
        if request.url.host == "github.com":
            return httpx.Response(302, headers={"Location": cdn + filename})
        assert request.url.host == "release-assets.githubusercontent.com"
        raw = (
            dumps(catalog) if filename == "catalog.json" else b"tampered" if tampered else b"image"
        )
        return httpx.Response(200, content=raw)

    manager = Manager(
        tmp_path / "state",
        tmp_path / "apps",
        client=httpx.Client(transport=httpx.MockTransport(serve)),
    )
    manager.configure(base + "/catalog.json")
    assert manager.catalog() == catalog
    assert manager.catalog(refresh=True) == catalog
    item = catalog.recipes[0].downloads["image.tar"]
    destination = tmp_path / "image.tar"
    if tampered:
        with pytest.raises(UpdateError) as error:
            manager._download(item.url, 1024, destination, item.digest)
        assert error.value.code == "artifact_mismatch"
    else:
        manager._download(item.url, 1024, destination, item.digest)
        assert destination.read_bytes() == b"image"
    assert requests == [
        base + "/catalog.json",
        cdn + "catalog.json",
        base + "/catalog.json",
        cdn + "catalog.json",
        base + "/image.tar",
        cdn + "image.tar",
    ]


def test_managed_rejected_redirect_does_not_create_payload(tmp_path):
    requests = []
    url = "https://github.com/example/apps/releases/download/initial/image.tar"

    def serve(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"Location": "http://evil.invalid/file"})

    manager = Manager(
        tmp_path / "state",
        tmp_path / "apps",
        client=httpx.Client(transport=httpx.MockTransport(serve)),
    )
    destination = tmp_path / "image.tar"
    with pytest.raises(UpdateError):
        manager._download(url, 1024, destination, digest(b"image"))
    assert requests == [url]
    assert not destination.exists()


APP = "flamoris-generation-mcp"
ORIGIN = "http://127.0.0.1:8764"


def recipe(release="1.0.0", application=APP):
    image = digest((application + release).encode())
    return {
        "application_id": application,
        "release": release,
        "platform": "linux/amd64",
        "compatible_from": ["1.0.0", "1.1.0", "1.2.0"],
        "settings": [{"key": "TOKEN", "label": "接続トークン", "secret": True, "required": True}],
        "downloads": {
            "image.tar": {
                "url": "https://releases.example.invalid/" + application + "/" + release + ".tar",
                "digest": digest(b"image"),
            }
        },
        "generated": {
            "runtime.env": "FLAMORIS_HTTP_HOST=127.0.0.1\nFLAMORIS_INTELLIGENCE_HTTP_HOST=127.0.0.1\nTOKEN=$TOKEN\n"
        },
        "application": {
            "kind": "docker",
            "application_id": application,
            "release": release,
            "image_id": image,
            "image_archive": {"path": "${package}/image.tar", "digest": digest(b"image")},
            "container_name": application,
            "environment_file": "${root}/config/runtime.env",
            "directories": [
                {"path": "${root}/config"},
                {"path": "${root}/data", "uid": 10001, "gid": 10001},
            ],
            "files": [
                {
                    "source": {
                        "path": "${package}/runtime.env",
                        "digest": "generated",
                        "private": True,
                    },
                    "destination": "${root}/config/runtime.env",
                }
            ],
            "mounts": [{"source": "${root}/data", "target": "/data", "read_only": False}],
            "health_url": "http://127.0.0.1:18765/healthz",
        },
    }


@pytest.fixture
def managed(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    # Some local containers map root alone. CI exercises actual UID changes;
    # local tests retain the command contract and byte/layout verification.
    original_chown = os.chown

    def chown(filename, uid, gid):
        try:
            original_chown(filename, uid, gid)
        except OSError as error:
            if error.errno != 22:
                raise

    monkeypatch.setattr(os, "chown", chown)
    catalog = {
        "catalog_version": 1,
        "recipes": [recipe(v) for v in ["1.0.0", "1.1.0", "1.2.0", "1.3.0"]],
    }
    calls = []
    containers = {}
    fail = {"health": False, "stop": False}

    def installer(cfg):
        app = cfg.applications[0]

        def command(argv, timeout=300):
            calls.append(argv)
            if argv[1:3] == ["container", "ls"]:
                return "\n".join(containers).encode()
            if argv[1:3] == ["image", "inspect"]:
                return json.dumps(
                    [
                        {
                            "Id": app.image_id,
                            "Os": "linux",
                            "Architecture": "amd64",
                            "Config": {
                                "Labels": {
                                    "org.opencontainers.image.version": app.release,
                                    "org.opencontainers.image.title": app.application_id,
                                    "net.flamoris.components": json.dumps(
                                        app.components
                                        or {"flamoris-generation-controller": "1.0.0"}
                                    ),
                                }
                            },
                        }
                    ]
                ).encode()
            if argv[1] == "stop":
                if fail["stop"]:
                    raise OSError("private diagnostic")
                containers[argv[-1]]["State"]["Running"] = False
            if argv[1] == "rename":
                containers[argv[3]] = containers.pop(argv[2])
            if argv[1] in {"run", "create"}:
                if argv[1] == "create":
                    assert "--detach" not in argv
                containers[app.container_name] = {
                    "Image": app.image_id,
                    "State": {"Running": argv[1] == "run"},
                    "Config": {"Env": [argv[i + 1] for i, a in enumerate(argv) if a == "--env"]},
                    "Mounts": [
                        {"Type": "bind", "Source": source, "Destination": "/data/music-output", "RW": True}
                        for source in app.output_directories.values() if source
                    ],
                }
            if argv[1] == "start":
                containers[argv[-1]]["State"]["Running"] = True
            if argv[1:3] == ["container", "inspect"]:
                return json.dumps(containers[argv[-1]]).encode()
            if argv[1:3] == ["container", "rm"]:
                del containers[argv[-1]]
            return b""

        def health(_):
            if fail["health"]:
                raise UpdateError("outcome_unknown")

        return Installer(cfg, command=command, health=health, unit_directory=tmp_path / "units")

    def http(request):
        if request.url.path == "/catalog.json":
            return httpx.Response(200, content=dumps(catalog))
        if request.url.path == "/api/v1/generation/system.health":
            return httpx.Response(200, json={"busy": fail.get("busy", False), "active_job_id": None})
        return httpx.Response(200, content=b"image")

    client = httpx.Client(transport=httpx.MockTransport(http))
    manager = Manager(tmp_path / "manager", tmp_path / "apps", installer=installer, client=client)
    return SimpleNamespace(
        manager=manager,
        catalog=catalog,
        calls=calls,
        containers=containers,
        fail=fail,
        tmp=tmp_path,
    )


def install(e, application=APP):
    job = e.manager.start(
        "install",
        Start(
            application_id=application,
            release="1.0.0",
            request_key="install-" + application,
            settings={"TOKEN": "keep-private-value"},
        ),
    )
    e.manager.run_job(job["job_id"])
    assert (
        e.manager.invoke("updater_managed_job_get", {"job_id": job["job_id"]})["phase"]
        == "awaiting_setup"
    )
    return job


def failed_stage(e):
    # Root-only user namespaces cannot chown to 10001; use an actual root-owned
    # recipe for recovery metadata tests. Normal installation CI covers 10001.
    for candidate in e.catalog["recipes"]:
        for directory in candidate["application"]["directories"]:
            directory.update(uid=0, gid=0)
    e.manager.configure("https://releases.example.invalid/catalog.json")
    factory = e.manager.installer

    def failed(cfg):
        instance = factory(cfg)

        def stage(_app):
            raise UpdateError("outcome_unknown")

        instance._stage = stage
        return instance

    e.manager.installer = failed
    job = e.manager.start(
        "install",
        Start(
            application_id=APP,
            release="1.0.0",
            request_key="failed-stage",
            settings={"TOKEN": "keep-private-value"},
        ),
    )
    e.manager.run_job(job["job_id"])
    e.manager.installer = factory
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "recovery_required"
    return job


def test_stage_recovery_retains_configuration_and_job_evidence(managed):
    from flamoris_updater_adapters.docker_stage_recovery import recover

    e = managed
    job = failed_stage(e)
    env = e.tmp / "apps" / APP / "config/runtime.env"
    before = env.read_bytes()
    calls = len(e.calls)
    assert recover(e.manager, job["job_id"])["applied"] is False
    assert not any(c[1] in {"load", "create", "run"} for c in e.calls[calls:])
    assert recover(e.manager, job["job_id"], apply=True)["phase"] == "awaiting_setup"
    assert env.read_bytes() == before
    assert e.manager.journal.get("managed_app", APP)["job_id"] == job["job_id"]
    recovered = e.manager.journal.get("managed_job", job["job_id"])
    assert recovered["recovered_failure"]["error"] == "outcome_unknown"
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    with pytest.raises(UpdateError):
        recover(e.manager, job["job_id"], apply=True)


@pytest.mark.parametrize(
    "change", ["configuration", "container", "later_step", "settings", "archive"]
)
def test_stage_recovery_refuses_changed_or_later_state(managed, change):
    from flamoris_updater_adapters.docker_stage_recovery import recover
    from flamoris_updater_adapters.journal import Journal

    e = managed
    job = failed_stage(e)
    if change == "configuration":
        (e.tmp / "apps" / APP / "config/runtime.env").write_bytes(b"modified")
    elif change == "container":
        e.containers[APP] = {"Image": "other", "State": {"Running": False}}
    elif change == "settings":
        (e.tmp / "manager/settings" / APP / "values.json").write_bytes(dumps({"TOKEN": "changed"}))
    elif change == "archive":
        (e.tmp / "manager/packages" / job["job_id"] / "image.tar").write_bytes(b"changed")
    else:
        journal = Journal(e.tmp / "manager/installer")
        record = journal.get("initial_install", APP)
        record["step"] = "provision"
        with journal.transaction() as db:
            journal.put("initial_install", APP, record, db)
    calls = len(e.calls)
    with pytest.raises(UpdateError):
        recover(e.manager, job["job_id"], apply=True)
    assert not any(c[1] in {"load", "create", "run"} for c in e.calls[calls:])
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "recovery_required"


def test_resolved_runtime_id_is_persisted_for_setup(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    factory = e.manager.installer
    actual = digest(b"containerd-runtime")

    def installer(cfg):
        instance = factory(cfg)
        stage, command = instance._stage, instance.command

        def resolve(app):
            stage(app)
            return app.model_copy(update={"image_id": actual})

        def execute(argv, **kwargs):
            result = command(argv, **kwargs)
            if argv[1] in {"run", "create"}:
                e.containers[APP]["Image"] = argv[-1]
            return result

        instance._stage, instance.command = resolve, execute
        return instance

    e.manager.installer = installer
    job = install(e)
    assert e.manager.journal.get("managed_app", APP)["profile"]["image_id"] == actual
    assert e.manager.layout(APP, job["job_id"])["candidate"]["image_id"] == actual
    e.manager.start_setup(APP)
    e.manager.complete(APP)


def update(e, release):
    job = e.manager.start(
        "update", Start(application_id=APP, release=release, request_key="update-" + release)
    )
    e.manager.run_job(job["job_id"])
    return e.manager.journal.get("managed_job", job["job_id"])


def test_empty_setup_install_update_keeps_settings_data_and_one_previous(managed):
    e = managed
    assert e.manager.invoke("updater_apps_list", {})["items"] == []
    e.manager.configure("https://releases.example.invalid/catalog.json")
    install(e)
    env = e.tmp / "apps" / APP / "config/runtime.env"
    retained = env.read_bytes()
    data = e.tmp / "apps" / APP / "data/history"
    data.write_bytes(b"irreplaceable")
    # App setup may edit its retained configuration independently of recipe inputs.
    env.write_bytes(retained + b"SETUP_FINISHED=yes\n")
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    for release in ["1.1.0", "1.2.0", "1.3.0"]:
        assert update(e, release)["phase"] == "succeeded"
        record = e.manager.journal.get("managed_app", APP)
        assert record["release"] == release and not record["older"]
        assert len(e.containers) == 2
        assert env.read_bytes() == retained + b"SETUP_FINISHED=yes\n"
        assert data.read_bytes() == b"irreplaceable"
    assert record["previous"]["release"] == "1.2.0"
    e.manager.delete_previous(APP)
    assert list(e.containers) == [APP]
    assert env.exists() and data.read_bytes() == b"irreplaceable"
    public = dumps(e.manager.invoke("updater_apps_list", {})) + dumps(
        e.manager.invoke("updater_managed_history", {})
    )
    assert b"keep-private-value" not in public


def test_later_second_application_does_not_import_existing_or_require_all_apps(managed):
    e = managed
    second = "flamoris-intelligence-mcp"
    e.catalog["recipes"].append(recipe(application=second))
    e.manager.configure("https://releases.example.invalid/catalog.json")
    install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    install(e, second)
    e.manager.start_setup(second)
    e.manager.complete(second)
    assert set(e.containers) == {APP, second}
    before = len(e.calls)
    with pytest.raises(UpdateError, match="Operation rejected"):
        e.manager.start(
            "install",
            Start(
                application_id=APP,
                release="1.0.0",
                request_key="other",
                settings={"TOKEN": "value"},
            ),
        )
    assert len(e.calls) == before


def test_dependency_only_blocks_actual_provider_and_incoming_consumer(managed):
    e = managed
    second = "flamoris-intelligence-mcp"
    consumer = recipe(application=second)
    consumer["dependencies"] = {APP: {"min_inclusive": "1.0.0", "max_exclusive": "1.1.0"}}
    e.catalog["recipes"].append(consumer)
    e.manager.configure("https://releases.example.invalid/catalog.json")
    args = Start(
        application_id=second, release="1.0.0", request_key="consumer", settings={"TOKEN": "value"}
    )
    with pytest.raises(UpdateError) as failure:
        e.manager.start("install", args)
    assert failure.value.code == "incompatible_dependency"
    install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    install(e, second)
    e.manager.start_setup(second)
    e.manager.complete(second)
    with pytest.raises(UpdateError) as failure:
        update(e, "1.1.0")
    assert failure.value.code == "incompatible_dependency"


@pytest.mark.parametrize("stage", ["stop", "health"])
def test_failed_update_keeps_every_previous_and_never_cleans_or_replays(managed, stage):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    assert update(e, "1.1.0")["phase"] == "succeeded"
    previous = copy.deepcopy(e.manager.journal.get("managed_app", APP)["previous"])
    e.fail[stage] = True
    job = update(e, "1.2.0")
    assert job["phase"] == "recovery_required"
    assert previous["container"] in e.containers
    assert not any(c[1:3] == ["container", "rm"] for c in e.calls)
    assert "private diagnostic" not in dumps(job).decode()
    count = len(e.calls)
    e.manager.run_job(job["job_id"])
    assert len(e.calls) == count
    with pytest.raises(UpdateError) as failure:
        e.manager.delete_previous(APP)
    assert failure.value.code == "busy"


def test_idempotency_conflict_and_changed_release_are_rejected(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    args = Start(
        application_id=APP, release="1.0.0", request_key="stable", settings={"TOKEN": "value"}
    )
    first = e.manager.start("install", args)
    assert e.manager.start("install", args)["job_id"] == first["job_id"]
    with pytest.raises(UpdateError) as failure:
        e.manager.start("install", args.model_copy(update={"settings": {"TOKEN": "different"}}))
    assert failure.value.code == "idempotency_conflict"
    before = e.manager.catalog()
    e.catalog["recipes"][0]["generated"]["runtime.env"] += "BAD=yes\n"
    assert e.manager.catalog(refresh=True) == before
    assert e.manager.catalog_errors
    assert e.manager.start("install", args)["job_id"] == first["job_id"]


def test_changed_queued_recipe_stops_before_effects_and_records_failure(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    job = e.manager.start(
        "install",
        Start(application_id=APP, release="1.0.0", request_key="corrupt", settings={"TOKEN": "x"}),
    )
    recorded = e.manager.journal.get("managed_recipe", job["job_id"])
    recorded["generated"]["runtime.env"] += "CHANGED=yes\n"
    e.manager.persist("managed_recipe", job["job_id"], recorded)
    e.manager.run_job(job["job_id"])
    failed = e.manager.journal.get("managed_job", job["job_id"])
    assert failed["phase"] == "recovery_required"
    assert failed["error"] == "journal_corrupt"
    assert not e.calls
    e.manager.run_job(job["job_id"])
    assert not e.calls


@pytest.mark.parametrize("value", ["${root}/../escape", "/etc/escape"])
def test_recipe_destinations_cannot_escape_application_root(managed, value):
    e = managed
    e.catalog["recipes"][0]["application"]["directories"][0]["path"] = value
    e.catalog["recipes"][0]["application"]["files"][0]["destination"] = value + "/runtime.env"
    e.catalog["recipes"][0]["application"]["environment_file"] = value + "/runtime.env"
    e.manager.configure("https://releases.example.invalid/catalog.json")
    job = e.manager.start(
        "install",
        Start(
            application_id=APP, release="1.0.0", request_key="escape", settings={"TOKEN": "value"}
        ),
    )
    e.manager.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "recovery_required"
    assert not e.calls


def test_cleanup_cannot_delete_data_via_corrupted_retained_pointer(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    record = e.manager.journal.get("managed_app", APP)
    data = e.tmp / "apps" / APP / "data"
    record["previous"] = {"kind": "native", "release": "1.0.0", "path": str(data)}
    e.manager.persist("managed_app", APP, record)
    with pytest.raises(UpdateError):
        e.manager.delete_previous(APP)
    assert data.exists()


def coordinator(e):
    class Direct:
        def call(self, packet):
            return loads(dispatch(e.manager, packet["action"], dumps(packet["body"])))

    cfg = BootstrapConfig(
        state_directory=str(e.tmp / "web"),
        helper_state_directory=str(e.tmp / "manager"),
        root=str(e.tmp / "apps"),
        socket_path=str(e.tmp / "ipc" / "manager.sock"),
        service_uid=10002,
        service_gid=10002,
        public_origin=ORIGIN,
    )
    c = LocalCoordinator(cfg, client=Direct())
    return c


def test_web_setup_then_web_mcp_cli_share_the_same_jobs(managed, monkeypatch, capfd):
    from flamoris_updater_adapters.cli import main

    e = managed
    c = coordinator(e)
    with TestClient(create_app(c, ORIGIN, run_worker=False), base_url=ORIGIN) as client:
        assert "リポジトリのカタログ" in client.get("/").text
        assert (
            client.post(
                "/api/v1/tools/updater_catalog_add",
                json={"url": "https://releases.example.invalid/catalog.json"},
            ).status_code
            == 200
        )
        headers = {}
        args = {
            "application_id": APP,
            "release": "1.0.0",
            "request_key": "all-interfaces",
            "settings": {"TOKEN": "private-test-value"},
        }
        job = client.post("/api/v1/tools/updater_install", json=args, headers=headers).json()
        assert job["phase"] == "accepted"
        token = ""
        result = mcp_call(
            client, token, "tools/call", {"name": "updater_install", "arguments": args}
        )
        assert result.status_code == 200, result.text
        assert result.json()["result"]["structuredContent"]["job_id"] == job["job_id"]
        monkeypatch.setattr("flamoris_updater_adapters.config.Endpoint.client", lambda _: client)
        main(
            [
                "job",
                "--url",
                ORIGIN,
                "--job-id",
                job["job_id"],
            ]
        )
        assert json.loads(capfd.readouterr().out)["job_id"] == job["job_id"]
        e.manager.run_job(job["job_id"])
        assert (
            client.post(
                "/api/v1/tools/updater_install_start", json={"application_id": APP}, headers=headers
            ).status_code
            == 200
        )
        assert (
            client.post(
                "/api/v1/tools/updater_install_complete",
                json={"application_id": APP},
                headers=headers,
            ).status_code
            == 200
        )
        changed = {"application_id": APP, "release": "1.1.0", "request_key": "mcp-update"}
        result = mcp_call(
            client, token, "tools/call", {"name": "updater_update", "arguments": changed}
        )
        update_job = result.json()["result"]["structuredContent"]
        e.manager.run_job(update_job["job_id"])
        assert (
            client.post(
                "/api/v1/tools/updater_managed_job_get",
                json={"job_id": update_job["job_id"]},
                headers=headers,
            ).json()["phase"]
            == "succeeded"
        )


def test_manager_socket_peer_checks_precede_configuration_or_operations(managed):
    e = managed
    for allowed in [[], [os.geteuid()]]:
        left, right = socket.socketpair()
        thread = threading.Thread(
            target=serve_connection, args=(right, e.manager, allowed, lambda: None, dispatch)
        )
        thread.start()
        raw = dumps(
            {
                "action": "configure",
                "body": {"catalog_url": "https://releases.exampl…19494 tokens truncated…
            while True:
                try:
                    if app.application_id == "flamoris-mcp-hub":
                        env = environment(protected_read(app.environment_file, private=True))
                        headers = {
                            "Accept": "application/json,text/event-stream",
                            "Authorization": "Bearer " + env["FLAMORIS_MCP_HUB_CLIENT_TOKEN"],
                        }
                        request = {
                            "jsonrpc": "2.0",
                            "id": "installation-health",
                            "method": "initialize",
                            "params": {
                                "protocolVersion": "2025-03-26",
                                "capabilities": {},
                                "clientInfo": {"name": "flamoris-updater", "version": "1.0.0"},
                            },
                        }
                        with client.stream(
                            "POST", app.health_url, json=request, headers=headers
                        ) as response:
                            if response.status_code == 200:
                                for line in response.iter_lines():
                                    if line.startswith("data: "):
                                        line = line[6:]
                                    if line.startswith("{"):
                                        body = json.loads(line)
                                        if (
                                            body.get("result", {})
                                            .get("serverInfo", {})
                                            .get("version")
                                            == app.release
                                        ):
                                            session = response.headers.get("mcp-session-id")
                                            if session:
                                                client.delete(
                                                    app.health_url,
                                                    headers={**headers, "mcp-session-id": session},
                                                )
                                            return
                    else:
                        r = client.get(app.health_url)
                        if r.status_code == 200:
                            return
                except httpx.HTTPError:
                    pass
                if time.monotonic() >= deadline:
                    raise UpdateError("outcome_unknown", "New application did not become healthy")
                time.sleep(0.25)

    def preflight(self):
        if os.geteuid() != 0 or socket.gethostname() != self.cfg.expected_hostname:
            raise UpdateError("forbidden", "Run locally as the expected host's administrator")
        actual = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
        if self.cfg.platform != actual:
            raise UpdateError("unsupported_platform")
        path(self.cfg.state_directory)
        for app in self.cfg.applications:
            for f in inputs(app):
                f.verify()
            for d in app.directories:
                absent(d.path)
            if isinstance(app, DockerApplication):
                names = self.command(
                    ["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"]
                )
                if app.container_name in names.decode().splitlines():
                    raise UpdateError("not_empty")
                source = next(f.source for f in app.files if f.destination == app.environment_file)
                env = environment(protected_read(source.path, private=source.private))
                if app.network == "host":
                    host_keys = {
                        "flamoris-ai-agent": "AGENT_HTTP_HOST",
                        "flamoris-generation-mcp": "FLAMORIS_HTTP_HOST",
                        "flamoris-intelligence-mcp": "FLAMORIS_INTELLIGENCE_HTTP_HOST",
                    }
                    host_key = host_keys.get(app.application_id)
                    if host_key and env.get(host_key) not in {"127.0.0.1", "::1"}:
                        raise UpdateError(
                            "invalid_profile", "Host-network services must bind loopback explicitly"
                        )
                for mount in app.mounts:
                    if mount.read_only and not any(
                        Path(mount.source).is_relative_to(d.path) for d in app.directories
                    ):
                        if not Path(mount.source).is_absolute() or not Path(mount.source).exists():
                            raise UpdateError(
                                "invalid_profile", "External read-only storage is missing"
                            )
            else:
                path(app.python)
                for unit in app.units:
                    absent(str(self.unit_directory / unit.name))
                    fragment = self.command(
                        [
                            "/usr/bin/systemctl",
                            "show",
                            unit.name,
                            "--property=FragmentPath",
                            "--value",
                        ]
                    )
                    if fragment.strip():
                        raise UpdateError("not_empty")
                    content = protected_read(unit.source.path).decode()
                    commands = [
                        line.strip()
                        for line in content.splitlines()
                        if line.strip().startswith("Exec")
                    ]
                    if (
                        len(commands) != 1
                        or not commands[0].startswith(f"ExecStart={app.venv}/bin/{app.entrypoint} ")
                        or "\\\n" in content
                    ):
                        raise UpdateError(
                            "invalid_profile", "Native unit must start the installed manager"
                        )
            if app.database:
                self._database_preflight(app)
        return {
            "applications": [
                {"application_id": a.application_id, "release": a.release}
                for a in self.cfg.applications
            ],
            "backup_required": False,
        }

    def _database_preflight(self, app):
        db = app.database
        with self.connect(db) as conn:
            if (
                conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (db.name,)).fetchone()
                or conn.execute(
                    "SELECT 1 FROM pg_roles WHERE rolname=ANY(%s)", ([db.owner, db.runtime_role],)
                ).fetchone()
            ):
                raise UpdateError(
                    "not_empty", "Application database and dedicated roles must be absent"
                )
        if isinstance(app, DockerApplication):
            from psycopg.conninfo import conninfo_to_dict

            source = next(f.source for f in app.files if f.destination == app.environment_file)
            env = environment(protected_read(source.path, private=source.private))
            admin = conninfo_to_dict(
                protected_read(db.admin_dsn.path, private=True).decode().strip()
            )
            if app.application_id == "flamoris-ai-agent":
                runtime = {
                    "dbname": env.get("PGDATABASE"),
                    "user": env.get("PGUSER"),
                    "host": env.get("PGHOST", ""),
                    "port": env.get("PGPORT", "5432"),
                    "password": env.get("PGPASSWORD"),
                }
            else:
                runtime = conninfo_to_dict(
                    env.get("STUDIO_DATABASE_URL", "").replace(
                        "postgresql+psycopg://", "postgresql://", 1
                    )
                )
            if (
                runtime.get("dbname") != db.name
                or runtime.get("user") != db.runtime_role
                or runtime.get("password")
                != protected_read(db.runtime_password.path, private=True).decode().rstrip("\n")
                or any(
                    runtime.get(k, "5432" if k == "port" else "")
                    != admin.get(k, "5432" if k == "port" else "")
                    for k in ("host", "port")
                )
            ):
                raise UpdateError(
                    "invalid_profile",
                    "Runtime credentials must target the new database and runtime role",
                )
        if db.studio_migration_environment:
            from psycopg.conninfo import conninfo_to_dict

            env = environment(protected_read(db.studio_migration_environment.path, private=True))
            url = env.get("STUDIO_DATABASE_URL", "").replace(
                "postgresql+psycopg://", "postgresql://", 1
            )
            target = conninfo_to_dict(url)
            admin = conninfo_to_dict(
                protected_read(db.admin_dsn.path, private=True).decode().strip()
            )
            if (
                target.get("dbname") != db.name
                or target.get("user") != db.owner
                or target.get("password")
                != protected_read(db.owner_password.path, private=True).decode().rstrip("\n")
                or any(
                    target.get(k, "5432" if k == "port" else "")
                    != admin.get(k, "5432" if k == "port" else "")
                    for k in ("host", "port")
                )
            ):
                raise UpdateError(
                    "invalid_profile", "Studio migration must target the new database and owner"
                )

    def _database_create(self, app):
        from psycopg import sql

        from .diagnostics import effect

        db = app.database
        with self.connect(db) as conn:
            for role, password in (
                (db.owner, db.owner_password),
                (db.runtime_role, db.runtime_password),
            ):
                value = protected_read(password.path, private=True).decode().rstrip("\n")
                effect(
                    "database.create_role",
                    lambda: conn.execute(
                        sql.SQL(
                            "CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}"
                        ).format(sql.Identifier(role), sql.Literal(value))
                    ),
                    {"role": role},
                )
            effect(
                "database.create",
                lambda: conn.execute(
                    sql.SQL("CREATE DATABASE {} OWNER {}").format(
                        sql.Identifier(db.name), sql.Identifier(db.owner)
                    )
                ),
                {"database": db.name, "owner_role": db.owner},
            )
            effect(
                "database.restrict_public",
                lambda: conn.execute(
                    sql.SQL("REVOKE ALL ON DATABASE {} FROM PUBLIC").format(sql.Identifier(db.name))
                ),
                {"database": db.name},
            )
            effect(
                "database.grant_runtime",
                lambda: conn.execute(
                    sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                        sql.Identifier(db.name), sql.Identifier(db.runtime_role)
                    )
                ),
                {"database": db.name, "runtime_role": db.runtime_role},
            )
        with self.connect(db, db.name) as conn:
            for f in db.sql_files:
                f.verify()
                effect(
                    "database.apply_initial_sql",
                    lambda: conn.execute(protected_read(f.path, limit=16 * 1024**2).decode()),
                    {"file": f.path, "digest": f.digest},
                )
        if db.studio_migration_environment:
            self.command(
                [
                    "/usr/bin/docker",
                    "run",
                    "--rm",
                    "--network",
                    "host",
                    "--env-file",
                    db.studio_migration_environment.path,
                    app.image_id,
                    "alembic",
                    "upgrade",
                    "head",
                ],
                timeout=300,
            )
        with self.connect(db, db.name) as conn:
            schemas = (
                ["public"]
                if app.application_id == "flamoris-studio"
                else ["core", "runtime", "chat", "memory", "relay", "ops"]
            )
            for schema in schemas:
                conn.execute(
                    sql.SQL("GRANT USAGE ON SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(db.runtime_role)
                    )
                )
                conn.execute(
                    sql.SQL(
                        "GRANT SELECT,INSERT,UPDATE,DELETE ON ALL TABLES IN SCHEMA {} TO {}"
                    ).format(sql.Identifier(schema), sql.Identifier(db.runtime_role))
                )
                conn.execute(
                    sql.SQL("GRANT USAGE,SELECT ON ALL SEQUENCES IN SCHEMA {} TO {}").format(
                        sql.Identifier(schema), sql.Identifier(db.runtime_role)
                    )
                )
                for privileges, objects in (
                    ("SELECT,INSERT,UPDATE,DELETE", "TABLES"),
                    ("USAGE,SELECT", "SEQUENCES"),
                ):
                    conn.execute(
                        sql.SQL(
                            "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA {} GRANT "
                            + privileges
                            + " ON "
                            + objects
                            + " TO {}"
                        ).format(
                            sql.Identifier(db.owner),
                            sql.Identifier(schema),
                            sql.Identifier(db.runtime_role),
                        )
                    )

    def _files(self, app):
        from .diagnostics import effect

        for d in app.directories:
            absent(d.path)
            effect(
                "files.create_directory",
                lambda: Path(d.path).mkdir(parents=True, mode=d.mode),
                {"path": d.path, "mode": d.mode},
            )
        for f in app.files:
            p = Path(f.destination)
            p.parent.mkdir(parents=True, exist_ok=True)

            def copy_file():
                durable_write(
                    p, protected_read(f.source.path, private=f.source.private), mode=f.mode
                )
                os.chown(p, f.uid, f.gid)

            effect(
                "files.copy_configuration",
                copy_file,
                {"destination": str(p), "mode": f.mode, "private": f.source.private},
            )
        # Ownership is applied only to new, explicit roots, never external model trees.
        for d in app.directories:

            def ownership():
                os.chown(d.path, d.uid, d.gid)
                os.chmod(d.path, d.mode)

            effect("files.set_ownership", ownership, d.model_dump())

    def _stage(self, app):
        if isinstance(app, DockerApplication):
            loaded = self.command(
                ["/usr/bin/docker", "load", "--input", app.image_archive.path], timeout=600
            )
            resolved = False
            try:
                image = json.loads(
                    self.command(["/usr/bin/docker", "image", "inspect", app.image_id])
                )[0]
            except UpdateError as error:
                detail = getattr(error, "diagnostic", {})
                if detail.get("kind") != "nonzero_exit" or detail.get("exit_code") != 1:
                    raise
                image = self._loaded_image(app, loaded)
                resolved = True
            runtime_id = image.get("Id")
            if not resolved and runtime_id != app.image_id:
                image = self._loaded_image(app, loaded)
                runtime_id = image.get("Id")
            if not isinstance(runtime_id, str) or not re.fullmatch(
                r"sha256:[0-9a-f]{64}", runtime_id
            ):
                raise UpdateError("artifact_mismatch")
            labels = image.get("Config", {}).get("Labels") or {}
            if (
                labels.get("org.opencontainers.image.version") != app.release
                or labels.get("org.opencontainers.image.title") != app.application_id
                or image.get("Config", {}).get("Volumes")
                or image.get("Os") != "linux"
                or image.get("Architecture") != self.cfg.platform.split("/")[1]
            ):
                raise UpdateError("artifact_mismatch")
            verify_components(app, labels)
            if runtime_id != app.image_id:
                from .diagnostics import event

                event(
                    "docker.image.resolve",
                    "verified",
                    {
                        "catalog_image_id": app.image_id,
                        "runtime_image_id": runtime_id,
                    },
                )
            return app.model_copy(update={"image_id": runtime_id})
        else:
            self.command([app.python, "-m", "venv", app.venv])
            self.command(
                [
                    app.venv + "/bin/python",
                    "-m",
                    "pip",
                    "install",
                    "--no-index",
                    "--no-deps",
                    *[f.path for f in app.wheels],
                ],
                timeout=600,
            )
            self.command([app.venv + "/bin/python", "-m", "pip", "check"])
            result = self.command(
                [
                    app.venv + "/bin/python",
                    "-c",
                    f"import importlib.metadata; print(importlib.metadata.version({app.distribution!r}))",
                ]
            )
            if result.strip().decode() != app.release:
                raise UpdateError("artifact_mismatch")
            return app

    def _loaded_image(self, app, loaded):
        """Bind containerd's manifest ID to the catalog's exact config digest.

        Docker's bounded load response supplies candidate references. A fresh,
        private export must contain the exact config blob before a candidate's
        immutable runtime ID can be used. Labels alone never establish identity.
        """
        references = re.findall(r"^Loaded image(?: ID)?: ([^\s]+)$", loaded.decode(), re.M)
        if not references or len(references) > 8:
            raise UpdateError("artifact_mismatch")
        for reference in references:
            if len(reference) > 256 or reference.startswith("-"):
                raise UpdateError("artifact_mismatch")
            image = json.loads(self.command(["/usr/bin/docker", "image", "inspect", reference]))[0]
            actual = image.get("Id", "")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", actual):
                raise UpdateError("artifact_mismatch")
            with tempfile.TemporaryDirectory(prefix="flamoris-image-") as directory:
                exported = Path(directory) / "image.tar"
                self.command(
                    ["/usr/bin/docker", "image", "save", "--output", str(exported), actual],
                    timeout=600,
                )
                if exported.stat().st_size > 4 * 1024**3:
                    raise UpdateError("quota_exceeded")
                if exported_config_matches(exported, app.image_id):
                    return image
        raise UpdateError("artifact_mismatch")

    def _start(self, app, *, start=True):
        if isinstance(app, DockerApplication):
            argv = [
                "/usr/bin/docker",
                "run" if start else "create",
                *(["--detach"] if start else []),
                "--name",
                app.container_name,
                "--restart",
                "unless-stopped",
                "--init",
                "--read-only",
                "--no-healthcheck",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges",
                "--pids-limit",
                "256",
                "--tmpfs",
                "/tmp:rw,nosuid,noexec,size=64m",
                "--user",
                "10001:10001",
                "--network",
                app.network,
                "--env-file",
                app.environment_file,
            ]
            if app.hostname:
                argv += ["--hostname", app.hostname]
            for port in app.ports:
                argv += ["--publish", f"127.0.0.1:{port.host}:{port.container}"]
            for m in app.mounts:
                argv += [
                    "--mount",
                    f"type=bind,src={m.source},dst={m.target}"
                    + (",readonly" if m.read_only else ""),
                ]
            if app.output_directories:
                from .outputs import TARGET, VARIABLE, check_directory

                source = app.output_directories["yue2"]
                check_directory(source, [d.path for d in app.directories] + [self.cfg.state_directory])
                if source:
                    argv += ["--mount", f"type=bind,src={source},dst={TARGET}"]
                argv += ["--env", VARIABLE + "=" + (TARGET if source else "")]
            if app.application_id == "flamoris-mcp-hub":
                env = environment(protected_read(app.environment_file, private=True))
                port = env.get("FLAMORIS_MCP_HUB_PORT", "8765")
                if not port.isdecimal() or not 1 <= int(port) <= 65535:
                    raise UpdateError("invalid_profile")
                self.command(
                    [
                        *argv,
                        app.image_id,
                        "flamoris-mcp-hub",
                        "--host",
                        "127.0.0.1" if app.network == "host" else "0.0.0.0",
                        "--port",
                        port,
                        "--mcp-path",
                        "/mcp",
                    ]
                )
            else:
                self.command([*argv, app.image_id])
        else:
            from .diagnostics import effect

            for unit in app.units:
                effect(
                    "unit.write",
                    lambda: durable_write(
                        self.unit_directory / unit.name,
                        protected_read(unit.source.path),
                        mode=0o644,
                    ),
                    {"unit": unit.name, "path": str(self.unit_directory / unit.name)},
                )
            self.command(["/usr/bin/systemctl", "daemon-reload"])
            self.command(
                [
                    "/usr/bin/systemctl",
                    "enable",
                    *(["--now"] if start else []),
                    *[u.name for u in app.units],
                ]
            )

    def _verify_running(self, app):
        if isinstance(app, DockerApplication):
            observed = json.loads(
                self.command(
                    [
                        "/usr/bin/docker",
                        "container",
                        "inspect",
                        "--format",
                        "{{json .}}",
                        app.container_name,
                    ]
                )
            )
            if (
                observed.get("Image") != app.image_id
                or observed.get("State", {}).get("Running") is not True
            ):
                raise UpdateError("outcome_unknown")
            if app.output_directories:
                from .outputs import TARGET, VARIABLE

                source = app.output_directories["yue2"]
                mounts = [m for m in observed.get("Mounts", []) if m.get("Destination") == TARGET]
                if (
                    (source and (len(mounts) != 1 or mounts[0].get("Type") != "bind" or mounts[0].get("Source") != source or mounts[0].get("RW") is not True))
                    or (not source and mounts)
                    or VARIABLE + "=" + (TARGET if source else "") not in (observed.get("Config", {}).get("Env") or [])
                ):
                    raise UpdateError("outcome_unknown", "Configured output binding was not applied")
        else:
            for u in app.units:
                if self.command(["/usr/bin/systemctl", "is-active", u.name]).strip() != b"active":
                    raise UpdateError("outcome_unknown")

    def apply(self, *, start=True):
        directory = path(self.cfg.state_directory)
        journal = Journal(directory)
        binding = digest(dumps(self.cfg))
        with exclusive(directory / "initial-install.lock"):
            for app in self.cfg.applications:
                previous = journal.get("initial_install", app.application_id)
                if previous:
                    raise UpdateError(
                        "already_installed"
                        if previous["phase"] == "succeeded"
                        else "recovery_required"
                    )
            from .diagnostics import effect as recorded_effect

            recorded_effect("installer.preflight", self.preflight)
            record = {
                "profile_digest": binding,
                "phase": "accepted",
                "application_id": None,
                "step": None,
            }

            def persist():
                with journal.transaction() as db:
                    for app in self.cfg.applications:
                        journal.put("initial_install", app.application_id, record, db)
                    journal.event(db, "initial_install", binding, record["phase"])
                journal.flush_export()

            persist()
            try:
                for app in self.cfg.applications:
                    steps = [("files", self._files), ("stage", self._stage)]
                    if app.database:
                        steps.append(("database", self._database_create))
                    steps.append(
                        ("start" if start else "provision", lambda a: self._start(a, start=start))
                    )
                    if start:
                        steps += [("health", self.health), ("verify_running", self._verify_running)]
                    for name, effect in steps:
                        for f in inputs(app):
                            f.verify()
                        record.update(phase="intent", application_id=app.application_id, step=name)
                        persist()
                        from .diagnostics import effect as recorded_effect

                        result = recorded_effect("installer." + name, lambda: effect(app))
                        if name == "stage" and isinstance(
                            result, (DockerApplication, NativeApplication)
                        ):
                            original = app
                            app = result
                            self.cfg = self.cfg.model_copy(
                                update={
                                    "applications": [
                                        app if item == original else item
                                        for item in self.cfg.applications
                                    ]
                                }
                            )
                        record["phase"] = "step_succeeded"
                        persist()
                record.update(
                    phase="succeeded" if start else "awaiting_setup", application_id=None, step=None
                )
                persist()
                return {
                    "phase": record["phase"],
                    "applications": [
                        {"application_id": a.application_id, "release": a.release}
                        for a in self.cfg.applications
                    ],
                    "backup_created": False,
                }
            except BaseException:
                record["phase"] = "recovery_required"
                persist()
                raise


def configured(filename):
    path(filename)
    return Installer(decode(Configuration, protected_read(filename, private=True, root_only=True)))

