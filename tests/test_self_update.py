"""Real indexed staging/journals/probes with isolated systemd effects; no live units."""

import io
import os
import subprocess
import tarfile
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.testclient import TestClient
from test_interfaces import mcp_call

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import digest, dumps, loads
from flamoris_updater_adapters.auth import AuthStore
from flamoris_updater_adapters.authority import Authority
from flamoris_updater_adapters.journal import Journal
from flamoris_updater_adapters.managed import MANAGED_TARGETS, Catalog, Manager
from flamoris_updater_adapters.self_update import (
    SELF,
    SelfRelease,
    Supervisor,
    unit_contents,
)
from flamoris_updater_adapters.setup import BootstrapConfig, LocalCoordinator, dispatch
from flamoris_updater_adapters.web import create_app

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="Protected supervisor runs in root CI")


def bundle():
    metadata = dict(
        compatibility_version=1,
        journal_version=1,
        control_store_version=1,
        recovery_protocol_version=1,
        package=SELF,
        version="1.1.0",
    )
    contents = {
        "bundle-compatibility.json": dumps(metadata),
        "bin/flamoris-updater-service": b"#!/usr/bin/python3.12\n# controlled candidate launcher\n",
        "site-packages/flamoris_updater_adapters/compatibility.py": Path(
            "src/flamoris_updater_adapters/compatibility.py"
        ).read_bytes(),
    }
    index = dumps(
        dict(
            content_index_version=1,
            platform="linux/amd64",
            python="3.12",
            files=[
                dict(path=n, digest=digest(b), size=len(b), executable=n.startswith("bin/"))
                for n, b in contents.items()
            ],
        )
    )
    contents["content-index.json"] = index
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, raw in contents.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(raw)
            entry.mode = 0o555 if name.startswith("bin/") else 0o444
            archive.addfile(entry, io.BytesIO(raw))
    blob = output.getvalue()
    release = SelfRelease(
        release="1.1.0",
        compatible_from=["1.0.0"],
        artifact=dict(
            kind="native",
            platform="linux/amd64",
            locator="https://release.example.invalid/updater.tar.gz",
            digest=digest(blob),
            content_index_digest=digest(index),
            max_expanded_bytes=sum(map(len, contents.values())),
        ),
    )
    return release, blob


@pytest.fixture
def updater(tmp_path, monkeypatch):
    monkeypatch.setattr("platform.machine", lambda: "x86_64")
    original = tmp_path / "bootstrap/bin/flamoris-updater-service"
    original.parent.mkdir(parents=True)
    original.write_text("original pinned installation")
    original.chmod(0o555)
    units = tmp_path / "units"
    units.mkdir()
    cfg = BootstrapConfig(
        state_directory=str(tmp_path / "web"),
        helper_state_directory=str(tmp_path / "manager"),
        root=str(tmp_path / "apps"),
        socket_path=str(tmp_path / "ipc/manager.sock"),
        service_uid=10002,
        service_gid=10002,
        public_origin="http://127.0.0.1:8764",
        bootstrap_executable=str(original),
        unit_directory=str(units),
    )
    config = tmp_path / "setup.json"
    config.write_bytes(dumps(cfg))
    for name, content in unit_contents(cfg, original, config).items():
        (units / name).write_text(content)
    pinned = units / "flamoris-updater-supervisor.service"
    pinned.write_text("pinned supervisor unit")
    web = Journal(tmp_path / "web")
    authority = Authority(web, lambda: 100)
    authority.provision("operator", ["read", "execute", "operator"], MANAGED_TARGETS)
    auth = AuthStore(web, authority, lambda: 100)
    key = auth.integration("operator", "persistent automation")
    release, blob = bundle()
    candidate = tmp_path / "releases" / release.artifact.digest.removeprefix("sha256:")
    wanted = dict(
        version="1.1.0",
        supervisor_protocol_version=1,
        integration_auth_version=1,
        runtime_root=str(candidate / "site-packages"),
    )
    calls, fail = [], {}

    def http(request):
        if request.url.path == "/catalog.json":
            return httpx.Response(
                200,
                content=dumps(Catalog(catalog_version=1, recipes=[], updater_releases=[release])),
            )
        if request.url.path == "/health":
            assert request.headers["Host"] == "127.0.0.1:8764"
            return httpx.Response(200, json=wanted)
        return httpx.Response(200, content=blob)

    client = httpx.Client(transport=httpx.MockTransport(http))
    manager = Manager(cfg.helper_state_directory, cfg.root, client=client, self_configuration=cfg)
    manager.configure("https://release.example.invalid/catalog.json")

    def command(argv, timeout=300):
        calls.append(argv)
        if len(argv) > 1 and fail.get(argv[1]):
            raise UpdateError("execution_failed")
        if argv[0] == "/usr/bin/systemctl":
            return b"active"
        if argv[0] == "/usr/bin/setpriv" or (len(argv) > 1 and argv[1] == "check"):
            return dumps({**wanted, **fail.get("identity", {})})
        # Compatibility.py actually inspects both SQLite databases in a subprocess.
        return subprocess.check_output(argv, timeout=timeout, stderr=subprocess.DEVNULL)

    supervisor = Supervisor(cfg, config, command=command, client=client)
    return SimpleNamespace(
        cfg=cfg,
        config=config,
        manager=manager,
        supervisor=supervisor,
        release=release,
        auth=auth,
        key=key,
        calls=calls,
        fail=fail,
        candidate=candidate,
        original=original,
        pinned=pinned,
    )


def accept(e):
    return e.manager.invoke("updater_self_update", dict(release="1.1.0", request_key="self-update"))


def test_updates_both_services_preserves_credentials_history_and_pinned_supervisor(updater):
    e = updater
    before_auth = e.auth.journal.get("integration", e.key["integration_id"])
    job = accept(e)
    assert accept(e)["job_id"] == job["job_id"]
    e.manager.run_job(job["job_id"])
    assert not e.calls  # Only the independent supervisor owns self Jobs.
    e.supervisor.run_job(job["job_id"])
    result = e.manager.invoke("updater_managed_job_get", {"job_id": job["job_id"]})
    assert result["phase"] == "succeeded", result
    assert result["verification"] == {"web_version": "1.1.0", "manager_version": "1.1.0"}
    assert [s["step"] for s in result["steps"] if s["outcome"] == "verified"] == [
        "stage",
        "stop",
        "control_check",
        "switch",
        "start",
        "verify",
    ]
    assert (
        e.manager.invoke("updater_self_status", {})["installation"]["previous"]["release"]
        == "1.0.0"
    )
    for name in unit_contents(e.cfg, e.original, e.config):
        assert str(e.candidate) in (Path(e.cfg.unit_directory) / name).read_text()
    assert e.pinned.read_text() == "pinned supervisor unit"
    assert e.original.read_text() == "original pinned installation"
    assert e.auth.journal.get("integration", e.key["integration_id"]) == before_auth
    restarted = AuthStore(Journal(e.auth.journal.directory), e.auth.authority, lambda: 99999999999)
    assert restarted.bearer(e.key["token"]) == e.key["integration_id"]
    assert e.key["token"].encode() not in dumps(result)


@pytest.mark.parametrize("failure", ["check", "stop", "daemon-reload", "start"])
def test_failure_is_recorded_without_replay_or_automatic_rollback(updater, failure):
    e = updater
    e.fail[failure] = True
    job = accept(e)
    e.supervisor.run_job(job["job_id"])
    failed = e.manager.journal.get("managed_job", job["job_id"])
    assert failed["phase"] == "recovery_required"
    assert failed["error"] == "execution_failed"
    assert failed["steps"][-1]["outcome"] == "intent"
    count = len(e.calls)
    e.supervisor.run_job(job["job_id"])
    assert len(e.calls) == count
    assert e.original.exists()
    with pytest.raises(UpdateError) as error:
        e.manager.invoke("updater_self_update", dict(release="1.1.0", request_key="retry"))
    assert error.value.code == "busy"
    with pytest.raises(UpdateError) as error:
        e.manager.invoke("updater_install_start", {"application_id": "flamoris-generation-mcp"})
    assert error.value.code == "busy"


def test_wrong_candidate_identity_is_rejected_before_stopping_services(updater):
    e = updater
    e.fail["identity"] = {"integration_auth_version": 2}
    job = accept(e)
    e.supervisor.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["error"] == "unsupported_journal"
    assert not any(c[0] == "/usr/bin/systemctl" for c in e.calls)


def test_incompatible_release_and_mutable_recipe_are_rejected(updater):
    e = updater
    with pytest.raises(UpdateError) as error:
        e.manager.invoke("updater_self_update", dict(release="1.0.0", request_key="old"))
    assert error.value.code == "release_unavailable"
    changed = e.release.model_copy(update={"compatible_from": []})
    with pytest.raises(UpdateError) as error:
        e.manager.accept_catalog(Catalog(catalog_version=1, recipes=[], updater_releases=[changed]))
    assert error.value.code == "operation_conflict"
    job = accept(e)
    e.manager.persist("managed_self_recipe", job["job_id"], changed.model_dump())
    e.supervisor.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["error"] == "journal_corrupt"
    assert not e.calls


def test_supervisor_restart_marks_unknown_and_manager_does_not_own_it(updater):
    e = updater
    job = accept(e)
    job.update(phase="intent", step="switch")
    e.supervisor.persist(job)
    e.manager.stopping.set()
    e.manager.worker()
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "intent"
    e.supervisor.stopping.set()
    e.supervisor.worker()
    result = e.manager.journal.get("managed_job", job["job_id"])
    assert result["phase"] == "recovery_required" and result["error"] == "outcome_unknown"
    assert not e.calls


def test_live_probe_waits_for_manager_socket_to_be_ready(updater):
    e = updater
    e.supervisor.candidate(e.release)
    original = e.supervisor.command
    attempts = []

    def delayed(argv, timeout=300):
        if argv[0] == "/usr/bin/setpriv":
            attempts.append(1)
            if len(attempts) == 1:
                raise UpdateError("execution_failed")
        return original(argv, timeout=timeout)

    e.supervisor.command = delayed
    assert (
        e.supervisor.probe(e.release, e.candidate / "bin/flamoris-updater-service")[
            "manager_version"
        ]
        == "1.1.0"
    )
    assert len(attempts) == 2


@pytest.mark.parametrize("changed", ["config", "unit"])
def test_changed_bootstrap_bindings_fail_before_effects(updater, changed):
    e = updater
    job = accept(e)
    if changed == "config":
        e.config.write_bytes(
            dumps(
                e.cfg.model_copy(
                    update={"listen_port": 8765, "public_origin": "http://127.0.0.1:8765"}
                )
            )
        )
    else:
        (Path(e.cfg.unit_directory) / "flamoris-updater.service").write_text(
            "changed by administrator"
        )
    e.supervisor.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["error"] == "operation_conflict"
    assert not e.calls


def test_mcp_reconnect_and_cli_share_the_self_update_job(updater, monkeypatch, capfd):
    from flamoris_updater_adapters.cli import main

    e = updater

    class Direct:
        def call(self, packet):
            return loads(dispatch(e.manager, packet["action"], dumps(packet["body"])))

    c = LocalCoordinator(e.cfg, client=Direct())
    with c.journal.transaction() as db:
        c.journal.put("web_setup", "completed", {"username": "operator"}, db)
    origin = e.cfg.public_origin

    def call(client, name, args):
        response = mcp_call(client, e.key["token"], "tools/call", {"name": name, "arguments": args})
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result["isError"], result
        return result["structuredContent"]

    with TestClient(create_app(c, c.auth, origin, run_worker=False), base_url=origin) as client:
        advertised = mcp_call(client, e.key["token"], "tools/list").json()["result"]["tools"]
        assert len(advertised) == 10
        job = call(client, "updater_self_update", {"release": "1.1.0", "request_key": "mcp-self"})
    e.supervisor.run_job(job["job_id"])
    # A new Web/coordinator instance uses the same state and Bearer key.
    c = LocalCoordinator(e.cfg, client=Direct())
    with TestClient(create_app(c, c.auth, origin, run_worker=False), base_url=origin) as client:
        result = call(client, "updater_managed_job_get", {"job_id": job["job_id"]})
        assert result["phase"] == "succeeded", result
        assert (
            call(client, "updater_self_update", {"release": "1.1.0", "request_key": "mcp-self"})[
                "job_id"
            ]
            == job["job_id"]
        )
        tokenfile = e.config.parent / "private-token"
        tokenfile.write_text(e.key["token"])
        tokenfile.chmod(0o600)
        monkeypatch.setattr("flamoris_updater_adapters.config.Endpoint.client", lambda _: client)
        main(["self-status", "--url", origin, "--token-file", str(tokenfile)])
        assert loads(capfd.readouterr().out.encode())["installation"]["release"] == "1.1.0"


def test_live_probe_rejects_wrong_runtime_even_when_health_is_200(updater, monkeypatch):
    e = updater
    e.supervisor.candidate(e.release)
    e.fail["identity"] = {"runtime_root": str(e.original.parent.parent / "site-packages")}
    clock = iter([0, 31])
    monkeypatch.setattr("flamoris_updater_adapters.self_update.time.monotonic", lambda: next(clock))
    with pytest.raises(UpdateError) as error:
        e.supervisor.probe(e.release, e.candidate / "bin/flamoris-updater-service")
    assert error.value.code == "outcome_unknown"
