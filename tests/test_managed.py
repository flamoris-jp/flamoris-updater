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
                                    "net.flamoris.components": '{"flamoris-generation-controller":"1.0.0"}',
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
                "body": {"catalog_url": "https://releases.example.invalid/catalog.json"},
            }
        )
        left.sendall(struct.pack("!I", len(raw)) + raw)
        size = struct.unpack("!I", left.recv(4))[0]
        response = loads(left.recv(size))
        thread.join(3)
        left.close()
        right.close()
        assert response == (
            {"error": "forbidden", "message": "Operation rejected"}
            if not allowed
            else {"configured": True}
        )


@pytest.mark.parametrize("prefix", ["", "/updater"])
def test_bootstrap_writes_only_new_services_with_unprivileged_web_and_local_helper(
    tmp_path, monkeypatch, prefix
):
    monkeypatch.setattr(os, "chown", lambda *_: None)
    units = tmp_path / "units"
    units.mkdir()
    executable = tmp_path / "flamoris-updater-service"
    executable.write_text("installed package launcher")
    executable.chmod(0o755)
    calls = []

    def command(argv):
        calls.append(argv)
        return b"isolated-test-setup-token-long-value\n" if argv[0] == "/usr/bin/setpriv" else b""

    base = tmp_path / "state"
    result = bootstrap(
        base,
        tmp_path / "apps",
        ORIGIN,
        command=command,
        account=SimpleNamespace(pw_uid=10002, pw_gid=10002),
        executable=str(executable),
        unit_directory=str(units),
        base_path=prefix,
    )
    assert result["url"] == ORIGIN + (prefix + "/" if prefix else "")
    assert "User=10002" in (units / "flamoris-updater.service").read_text()
    cfg = json.loads((base / "setup.json").read_bytes())
    assert cfg["base_path"] == prefix
    assert cfg["listen_host"] == "127.0.0.1" and cfg["service_uid"] == 10002
    assert "setup_token" not in result
    assert not any(call[0] == "/usr/bin/setpriv" for call in calls)
    with pytest.raises(UpdateError):
        bootstrap(base, tmp_path / "apps", ORIGIN, command=command)


def test_all_portable_recipes_compile_without_operator_profile_json(managed):
    from flamoris_updater_adapters.install import VERSIONS

    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    for application, release in VERSIONS.items():
        item = {
            "application_id": application,
            "release": release,
            "platform": "linux/amd64",
            "image_id": digest(b"image-id"),
            "files": {
                n: digest(b"image") for n in ["image.tar", "db/01_schema.sql", "manager.whl"]
            },
        }
        built = build_recipe(item, "https://releases.example.invalid/candidate")
        with e.manager.journal.transaction() as db:
            e.manager.journal.put(
                "manager_catalog",
                "current",
                {"catalog_version": 1, "recipes": [built.model_dump()]},
                db,
            )
        args = Start(
            application_id=application,
            release=release,
            request_key=application,
            settings={
                "ADMIN_DSN": "postgresql://admin@database.example.invalid/postgres",
                "PGHOST": "database.example.invalid",
            }
            if application in {"flamoris-ai-agent", "flamoris-studio"}
            else {},
        )
        job = e.manager.start("install", args)
        compiled = e.manager._profile(built, job["job_id"])
        assert compiled.applications[0].application_id == application
        e.manager.persist("managed_job", job["job_id"], {**job, "phase": "succeeded"})


def wheel(release):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        prefix = "flamoris_gpu_node_manager-" + release + ".dist-info/"
        archive.writestr(
            prefix + "METADATA",
            "Metadata-Version: 2.1\nName: flamoris-gpu-node-manager\nVersion: " + release + "\n",
        )
        archive.writestr(
            prefix + "WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr(prefix + "RECORD", "")
        archive.writestr(
            prefix + "entry_points.txt", "[console_scripts]\ngpu-node-manager = fake_manager:main\n"
        )
        archive.writestr("fake_manager.py", "def main():\n    return None\n")
    return buffer.getvalue()


def test_native_real_offline_venvs_keep_runtime_profiles_and_only_one_previous(
    tmp_path, monkeypatch
):
    app = "flamoris-gpu-node-manager"
    releases = ["1.2.0", "1.3.0", "1.4.0"]
    blobs = {release: wheel(release) for release in releases}
    recipes = []
    interpreter = tmp_path / "python312"
    binary = str(Path(sys.executable).resolve())
    interpreter.write_text(
        "#!/usr/bin/python3\nimport os,sys\nos.execv("
        + repr(binary)
        + ",["
        + repr(binary)
        + ",*sys.argv[1:]])\n"
    )
    interpreter.chmod(0o755)
    for release in releases:
        filename = "flamoris_gpu_node_manager-" + release + "-py3-none-any.whl"
        built = build_recipe(
            {
                "application_id": app,
                "release": release,
                "platform": "linux/amd64",
                "compatible_from": releases[: releases.index(release)],
                "files": {filename: digest(blobs[release])},
            },
            "https://releases.example.invalid/" + release,
        )
        spec = built.application.copy()
        spec["python"] = str(interpreter)
        recipes.append(built.model_copy(update={"application": spec}))
    catalog = Catalog(catalog_version=1, recipes=recipes)

    def http(request):
        if request.url.path == "/catalog.json":
            return httpx.Response(200, content=dumps(catalog))
        return httpx.Response(200, content=blobs[request.url.path.split("/")[1]])

    units = tmp_path / "units"
    units.mkdir()
    active = set()

    def installer(cfg):
        def command(argv, timeout=300):
            if argv[0] == "/usr/bin/systemctl":
                if argv[1] in {"start", "enable"} and (argv[1] == "start" or "--now" in argv):
                    active.update(u.name for u in cfg.applications[0].units)
                if argv[1] == "stop":
                    active.clear()
                if argv[1] == "is-active":
                    return b"active" if argv[2] in active else b"inactive"
                return b""
            return subprocess.check_output(argv, stderr=subprocess.DEVNULL, timeout=timeout)

        return Installer(cfg, command=command, health=lambda _: None, unit_directory=str(units))

    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    manager = Manager(
        tmp_path / "manager",
        tmp_path / "apps",
        installer=installer,
        client=httpx.Client(transport=httpx.MockTransport(http)),
    )
    manager.configure("https://releases.example.invalid/catalog.json")
    job = manager.start(
        "install", Start(application_id=app, release=releases[0], request_key="native")
    )
    manager.run_job(job["job_id"])
    assert manager.journal.get("managed_job", job["job_id"])["phase"] == "awaiting_setup", (
        manager.journal.get("managed_job", job["job_id"])
    )
    assert not active
    runtime = tmp_path / "apps" / app / "runtimes" / "operator.yaml"
    runtime.write_text("operator-owned runtime settings")
    manager.start_setup(app)
    manager.complete(app)
    for release in releases[1:]:
        job = manager.start(
            "update", Start(application_id=app, release=release, request_key=release)
        )
        manager.run_job(job["job_id"])
        assert manager.journal.get("managed_job", job["job_id"])["phase"] == "succeeded"
    directory = tmp_path / "apps" / app / "releases"
    assert sorted(p.name for p in directory.iterdir()) == ["1.3.0", "1.4.0"]
    assert "releases/1.4.0/bin/gpu-node-manager" in next(units.iterdir()).read_text()
    manager.delete_previous(app)
    assert sorted(p.name for p in directory.iterdir()) == ["1.4.0"]
    assert runtime.read_text() == "operator-owned runtime settings"


def read_all_logs(manager, job):
    items, after = [], 0
    while True:
        page = manager.invoke(
            "updater_managed_log_get",
            {"application_id": APP, "job_id": job["job_id"], "after": after, "limit": 10},
        )
        items.extend(page["items"])
        if not page["has_more"]:
            return items
        after = page["next_after"]


def test_diagnostics_cover_install_setup_failed_update_and_layout(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    first = install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    initial = read_all_logs(e.manager, first)
    assert {
        "installer.files",
        "installer.stage",
        "installer.provision",
        "setup.health",
        "setup.verify_running",
    } <= {r["operation"] for r in initial}
    assert any(r["operation"] == "docker.start" and r["outcome"] == "completed" for r in initial)
    e.fail["health"] = True
    failed = update(e, "1.1.0")
    timeline = read_all_logs(e.manager, failed)
    assert any(r["operation"] == "switch" and r["outcome"] == "completed" for r in timeline)
    assert any(r["operation"] == "health" and r["outcome"] == "failed" for r in timeline)
    assert failed["failure"]["error"] == "outcome_unknown"
    layout = e.manager.invoke(
        "updater_managed_layout_get", {"application_id": APP, "job_id": failed["job_id"]}
    )
    assert layout["live_state"] is False
    assert layout["current"]["release"] == "1.0.0"
    assert layout["candidate"]["release"] == "1.1.0"
    assert layout["candidate"]["previous_layout"]["release"] == "1.0.0"
    assert layout["current"]["configuration"][0]["path"].endswith("config/runtime.env")
    assert layout["current"]["mounts"][0]["source"].endswith("data")
    assert b"keep-private-value" not in dumps(layout)
    assert b"keep-private-value" not in dumps(timeline)
    assert b"private diagnostic" not in dumps(timeline)
    for p in (e.tmp / "manager/diagnostics").glob("job-*"):
        assert b"keep-private-value" not in p.read_bytes()
    with pytest.raises(UpdateError) as mismatch:
        e.manager.invoke(
            "updater_managed_log_get",
            {"application_id": "flamoris-studio", "job_id": failed["job_id"]},
        )
    assert mismatch.value.code == "invalid_input"


def test_mcp_reads_evidence_without_an_integration_key(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    job = install(e)
    c = coordinator(e)
    with TestClient(create_app(c, ORIGIN, run_worker=False), base_url=ORIGIN) as client:
        response = mcp_call(
            client,
            "",
            "tools/call",
            {
                "name": "updater_managed_log_get",
                "arguments": {"application_id": APP, "job_id": job["job_id"]},
            },
        )
        assert response.status_code == 200
        assert not response.json()["result"]["isError"]


def test_interrupted_intent_keeps_timeline_and_is_not_replayed(managed):
    from flamoris_updater_adapters.diagnostics import event, recording

    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    job = e.manager.start(
        "install",
        Start(
            application_id=APP,
            release="1.0.0",
            request_key="interrupted-log",
            settings={"TOKEN": "keep-private-value"},
        ),
    )
    with recording(e.manager.journal, job["job_id"]):
        event("switch", "intent")
    job.update(phase="intent", step="switch")
    e.manager.persist("managed_job", job["job_id"], job)
    e.manager.stopping.set()
    e.manager.worker()
    assert not e.calls
    record = e.manager.journal.get("managed_job", job["job_id"])
    assert record["failure"]["kind"] == "interrupted"
    entries = read_all_logs(e.manager, job)
    assert entries[0]["outcome"] == "intent"
    assert entries[1]["operation"] == "job.interrupted" and entries[1]["outcome"] == "unknown"


def test_prefixed_catalog_screen_and_mcp_without_first_setup(managed):
    c = coordinator(managed)
    with TestClient(
        create_app(c, ORIGIN, run_worker=False, base_path="/updater"), base_url=ORIGIN
    ) as client:
        assert "リポジトリのカタログ" in client.get("/updater/").text
        for asset in ["managed.js", "style.css"]:
            assert client.get("/updater/static/" + asset).status_code == 200
        assert (
            client.post(
                "/updater/api/v1/tools/updater_catalog_add",
                json={"url": "https://releases.example.invalid/catalog.json"},
            ).status_code
            == 200
        )
        assert mcp_call(client, "", "tools/list", path="/updater/mcp").status_code == 200
        assert client.get("/api/v1/tools/updater_apps_list").status_code == 404


def test_repository_catalogs_refresh_independently_without_payload_copy(managed):
    e = managed
    second = "example-private-manager"
    sources = {
        "https://github.com/example/generation/releases/latest/download/catalog.json": {
            "catalog_version": 1,
            "recipes": [recipe()],
        },
        "https://catalog.example.invalid/private/catalog.json": {
            "catalog_version": 1,
            "recipes": [recipe(application=second)],
        },
    }
    requested = []

    def respond(request):
        url = str(request.url)
        requested.append(url)
        return (
            httpx.Response(200, content=dumps(sources[url]))
            if url in sources
            else httpx.Response(200, content=b"image")
        )

    e.manager.client = httpx.Client(transport=httpx.MockTransport(respond))
    urls = list(sources)
    for url in urls:
        e.manager.invoke("updater_catalog_add", {"url": url})
    assert e.manager.sources() == urls
    assert all(url in sources for url in requested)  # Catalog registration downloads no payload.
    apps = e.manager.invoke("updater_apps_list", {})["items"]
    assert {app["application_id"] for app in apps} == {APP, second}
    install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    install(e, second)
    e.manager.start_setup(second)
    e.manager.complete(second)
    sources[urls[0]]["recipes"].append(recipe("1.1.0"))
    e.manager.invoke("updater_apps_list", {"refresh": True})
    assert update(e, "1.1.0")["phase"] == "succeeded"
    assert e.manager.journal.get("managed_app", second)["release"] == "1.0.0"
    e.manager.invoke("updater_catalog_remove", {"url": urls[1]})
    assert e.manager.sources() == urls[:1]
    app = next(
        a
        for a in e.manager.invoke("updater_apps_list", {})["items"]
        if a["application_id"] == second
    )
    assert app["installation"]["phase"] == "succeeded" and app["releases"] == []
    assert second in e.containers


def test_catalog_conflict_and_failed_refresh_leave_existing_sources_intact(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    original = e.manager.catalog()
    changed = recipe()
    changed["downloads"]["image.tar"]["digest"] = digest(b"changed")
    e.manager.client = httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, content=dumps({"catalog_version": 1, "recipes": [changed]})
            )
        )
    )
    with pytest.raises(UpdateError):
        e.manager.configure("https://another.example.invalid/catalog.json")
    assert e.manager.sources() == ["https://releases.example.invalid/catalog.json"]
    assert e.manager.catalog() == original
    assert e.manager.catalog(refresh=True) == original
    assert e.manager.catalog_errors
    assert e.manager.catalog() == original


def test_legacy_single_catalog_record_still_loads_without_web_account(managed):
    e = managed
    e.manager.configure("https://releases.example.invalid/catalog.json")
    with e.manager.journal.transaction() as db:
        e.manager.journal.put(
            "manager_config", "source", {"url": "https://releases.example.invalid/catalog.json"}, db
        )
    c = coordinator(e)
    assert c.managed_invoke("local", "updater_apps_list", {})["items"]
    assert e.manager.catalog(refresh=True).recipes


def test_one_offline_repository_does_not_block_another_refresh_or_catalog_removal(managed):
    e = managed
    first = "https://first.example.invalid/catalog.json"
    second = "https://second.example.invalid/catalog.json"
    catalogs = {
        first: {"catalog_version": 1, "recipes": [recipe()]},
        second: {"catalog_version": 1, "recipes": [recipe(application="example-other-app")]},
    }
    offline = set()

    def respond(request):
        url = str(request.url)
        if url in offline:
            return httpx.Response(503)
        return httpx.Response(200, content=dumps(catalogs[url]))

    e.manager.client = httpx.Client(transport=httpx.MockTransport(respond))
    e.manager.configure(first)
    offline.add(first)
    # Registration needs only the newly selected repository, not every source online.
    e.manager.configure(second)
    catalogs[second]["recipes"].append(recipe("1.1.0", application="example-other-app"))
    refreshed = e.manager.invoke("updater_apps_list", {"refresh": True})
    assert refreshed["catalog_errors"] == [{"url": first, "error": "catalog_refresh_failed"}]
    other = next(app for app in refreshed["items"] if app["application_id"] == "example-other-app")
    assert [r["release"] for r in other["releases"]] == ["1.0.0", "1.1.0"]
    offline.add(second)
    e.manager.remove_source(first)
    assert e.manager.sources() == [second]
