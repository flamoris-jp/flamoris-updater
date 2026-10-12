"""Known media binding configuration uses the managed Job path and real storage."""

import copy
import os
from pathlib import Path

import httpx
import pytest
from test_managed import APP, install, managed  # noqa: F401

from flamoris_update_core.errors import UpdateError
from flamoris_updater_adapters.outputs import check_directory, directory_syntax

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="Root filesystem CI")


def setup(e, monkeypatch):
    for recipe in e.catalog["recipes"]:
        recipe["application"]["mounts"][0]["target"] = "/data/private"
        recipe["application"]["components"] = {"flamoris-generation-controller": "1.0.1"}
    e.manager.configure("https://releases.example.invalid/catalog.json")
    installed = install(e)
    e.manager.start_setup(APP)
    e.manager.complete(APP)
    env = Path(e.manager.journal.get("managed_app", APP)["profile"]["environment_file"])
    env.write_bytes(env.read_bytes() + b"FLAMORIS_CONTROLLER_TOKEN=" + b"a" * 32 + b"\n")
    monkeypatch.setattr("flamoris_updater_adapters.outputs.writable_by_runtime", lambda _: True)
    media = e.tmp / "media"
    media.mkdir(mode=0o2755)
    (media / "existing.wav").write_bytes(b"keep-existing")
    return installed, media, env


def configure(e, directory, key="output-choice"):
    return e.manager.invoke("updater_outputs_configure", {"application_id": APP, "request_key": key, "directories": {"yue2": str(directory)}})


def test_configuration_survives_manager_restart_and_release_update(managed, monkeypatch):
    e = managed
    package, media, env = setup(e, monkeypatch)
    before = env.read_bytes()
    metadata = media.stat()
    job = configure(e, media)
    assert configure(e, media)["job_id"] == job["job_id"]
    with pytest.raises(UpdateError) as err:
        configure(e, "", key="output-choice")
    assert err.value.code == "idempotency_conflict"
    calls = len(e.calls)
    e.manager.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "succeeded"
    assert not any(c[1] == "load" for c in e.calls[calls:])
    current = e.manager.journal.get("managed_app", APP)
    assert current["job_id"] == package["job_id"]
    assert current["configuration_job_id"] == job["job_id"]
    assert current["profile"]["output_directories"] == {"yue2": str(media)}
    run = next(c for c in e.calls[calls:] if c[1] == "run")
    assert "type=bind,src=" + str(media) + ",dst=/data/music-output" in run
    assert "FLAMORIS_YUE2_OUTPUT_ROOT=/data/music-output" in run
    assert env.read_bytes() == before
    assert (media / "existing.wav").read_bytes() == b"keep-existing"
    assert (media.stat().st_mode, media.stat().st_uid, media.stat().st_gid) == (metadata.st_mode, metadata.st_uid, metadata.st_gid)
    from flamoris_updater_adapters.managed import Manager, Start

    e.manager = Manager(e.manager.state, e.manager.root, installer=e.manager.installer, client=e.manager.client)
    upgrade = e.manager.start("update", Start(application_id=APP, release="1.1.0", request_key="next-version"))
    e.manager.run_job(upgrade["job_id"])
    assert e.manager.journal.get("managed_job", upgrade["job_id"])["phase"] == "succeeded"
    assert e.manager.journal.get("managed_app", APP)["profile"]["output_directories"] == {"yue2": str(media)}
    assert media.exists() and (media / "existing.wav").read_bytes() == b"keep-existing"
    assert env.read_bytes() == before


def test_disable_and_previous_cleanup_keep_media_and_current_package(managed, monkeypatch):
    e = managed
    package, media, _ = setup(e, monkeypatch)
    first = configure(e, media)
    e.manager.run_job(first["job_id"])
    job = configure(e, "", key="disable-output")
    e.manager.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["phase"] == "succeeded"
    assert any("FLAMORIS_YUE2_OUTPUT_ROOT=" in c for c in e.calls if c[1] == "run")
    e.manager.delete_previous(APP)
    assert (e.manager.state / "packages" / package["job_id"]).exists()
    assert (media / "existing.wav").read_bytes() == b"keep-existing"


@pytest.mark.parametrize("bad", ["missing", "symlink", "state", "app", "permission"])
def test_invalid_media_directory_has_no_container_effect(managed, monkeypatch, bad):
    e = managed
    _, media, _ = setup(e, monkeypatch)
    if bad == "missing":
        media = e.tmp / "absent"
    elif bad == "symlink":
        alias = e.tmp / "alias"
        alias.symlink_to(media, target_is_directory=True)
        media = alias
    elif bad == "state":
        media = e.manager.state
    elif bad == "app":
        media = e.manager.root / APP / "data"
    else:
        monkeypatch.setattr("flamoris_updater_adapters.outputs.writable_by_runtime", lambda _: False)
    calls = len(e.calls)
    with pytest.raises(UpdateError):
        configure(e, media)
    assert len(e.calls) == calls


@pytest.mark.parametrize("failure", ["busy", "health"])
def test_execution_failure_keeps_old_binding_and_records_no_replay(managed, monkeypatch, failure):
    e = managed
    _, media, _ = setup(e, monkeypatch)
    before = copy.deepcopy(e.manager.journal.get("managed_app", APP)["profile"])
    job = configure(e, media)
    e.fail[failure] = True
    calls = len(e.calls)
    e.manager.run_job(job["job_id"])
    failed = e.manager.journal.get("managed_job", job["job_id"])
    assert failed["phase"] == "recovery_required"
    assert e.manager.journal.get("managed_app", APP)["profile"] == before
    if failure == "busy":
        assert not any(c[1] == "stop" for c in e.calls[calls:])
    else:
        assert "retained_candidate" in failed
    calls = len(e.calls)
    e.manager.run_job(job["job_id"])
    assert len(e.calls) == calls


def test_changed_profile_between_admission_and_execution_stops(managed, monkeypatch):
    e = managed
    _, media, _ = setup(e, monkeypatch)
    job = configure(e, media)
    installed = e.manager.journal.get("managed_app", APP)
    installed["profile"]["health_timeout_seconds"] = 12
    e.manager.persist("managed_app", APP, installed)
    calls = len(e.calls)
    e.manager.run_job(job["job_id"])
    assert e.manager.journal.get("managed_job", job["job_id"])["error"] == "operation_conflict"
    assert len(e.calls) == calls


@pytest.mark.parametrize("source", ["/", "/srv", "/etc/secrets", "/run/docker", "/data/../private", "relative/path", "/data/media,readonly", "/data/media\nnext"])
def test_reject_unsafe_directory_syntax(source):
    with pytest.raises(ValueError):
        directory_syntax(source)


def test_runtime_permission_check_observes_uid_and_parent_traversal(tmp_path):
    for parent in [tmp_path, *tmp_path.parents]:
        if parent == Path("/tmp"):
            break
        os.chmod(parent, 0o755)
    media = tmp_path / "public"
    media.mkdir(mode=0o700)
    with pytest.raises(UpdateError):
        check_directory(str(media), [])
    os.chown(media, 10001, 10001)
    check_directory(str(media), [])
    os.chmod(tmp_path, 0o700)
    with pytest.raises(UpdateError):
        check_directory(str(media), [])


def test_idle_http_has_bounded_body_and_no_redirect(managed, monkeypatch):
    from flamoris_updater_adapters.outputs import idle
    from flamoris_updater_adapters.install import DockerApplication

    e = managed
    setup(e, monkeypatch)
    app = DockerApplication.model_validate(e.manager.journal.get("managed_app", APP)["profile"])
    e.manager.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b"x" * 262145)))
    with pytest.raises(UpdateError):
        idle(e.manager, app)
