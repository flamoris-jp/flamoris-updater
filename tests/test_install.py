"""Fresh local installation effects and failures; no production services or inference."""

import json
import os
import platform
import socket

import pytest
from pydantic import ValidationError

from flamoris_update_core.errors import UpdateError
from flamoris_update_core.wire import decode, digest, dumps
from flamoris_updater_adapters.install import Configuration, File, Installer, environment
from flamoris_updater_adapters.journal import Journal

pytestmark = pytest.mark.skipif(
    os.geteuid() != 0, reason="Protected local installer tests run as root in CI"
)


def local_file(path, content=b"candidate", private=False):
    path.write_bytes(content)
    path.chmod(0o600 if private else 0o644)
    return {"path": str(path), "digest": digest(content), "private": private}


@pytest.fixture
def installation(tmp_path):
    image = digest(b"installed-image")
    root = tmp_path / "application"
    external = tmp_path / "external-models"
    external.mkdir()
    (external / "model").write_bytes(b"keep shared model")
    env = local_file(tmp_path / "runtime-input", b"FLAMORIS_HTTP_HOST=127.0.0.1\n", True)
    cfg = Configuration.model_validate(
        {
            "install_profile_version": 1,
            "expected_hostname": socket.gethostname(),
            "platform": {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}[platform.machine()],
            "state_directory": str(tmp_path / "history"),
            "applications": [
                {
                    "kind": "docker",
                    "application_id": "flamoris-generation-mcp",
                    "release": "1.0.0",
                    "image_archive": local_file(tmp_path / "image.tar"),
                    "image_id": image,
                    "container_name": "flamoris-test-generation",
                    "environment_file": str(root / ".env"),
                    "directories": [{"path": str(root)}],
                    "files": [{"source": env, "destination": str(root / ".env")}],
                    "mounts": [
                        {"source": str(external), "target": "/data/models", "read_only": True}
                    ],
                    "health_url": "http://127.0.0.1:8765/healthz",
                }
            ],
        }
    )
    calls = []

    def command(argv, timeout=300):
        calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return json.dumps(
                [
                    {
                        "Id": image,
                        "Os": "linux",
                        "Architecture": cfg.platform.split("/")[1],
                        "Config": {
                            "Labels": {
                                "org.opencontainers.image.version": "1.0.0",
                                "org.opencontainers.image.title": "flamoris-generation-mcp",
                                "net.flamoris.components": '{"flamoris-generation-controller":"1.0.0"}',
                            }
                        },
                    }
                ]
            ).encode()
        if argv[1:3] == ["container", "inspect"]:
            return json.dumps({"Image": image, "State": {"Running": True}}).encode()
        return b""

    return cfg, Installer(cfg, command=command, health=lambda _: None), calls, external


def test_empty_install_succeeds_without_owner_endpoint_or_backup(installation):
    cfg, installer, calls, external = installation
    # Strict JSON round-trip exercises the actual profile parser.
    assert decode(Configuration, dumps(cfg)) == cfg
    assert installer.apply()["phase"] == "succeeded"
    assert (external / "model").read_bytes() == b"keep shared model"
    assert (external.stat().st_uid, external.stat().st_mode & 0o777) == (0, 0o755)
    assert all(argv[0] == "/usr/bin/docker" for argv in calls)
    assert not any(word in argv for argv in calls for word in ("rm", "stop", "exec", "build"))
    with pytest.raises(UpdateError) as e:
        installer.apply()
    assert e.value.code == "already_installed"


def test_existing_data_rejected_before_package_or_service_effect(installation):
    cfg, installer, calls, _ = installation
    root = cfg.applications[0].directories[0].path
    from pathlib import Path

    Path(root).mkdir()
    (Path(root) / "keep").write_bytes(b"existing")
    with pytest.raises(UpdateError) as e:
        installer.apply()
    assert e.value.code == "not_empty"
    assert (Path(root) / "keep").read_bytes() == b"existing"
    assert not calls


def test_wrong_host_or_operator_has_no_effect(installation, monkeypatch):
    _, installer, calls, _ = installation
    monkeypatch.setattr(socket, "gethostname", lambda: "different-host")
    with pytest.raises(UpdateError) as e:
        installer.preflight()
    assert e.value.code == "forbidden" and not calls
    monkeypatch.setattr(socket, "gethostname", lambda: installer.cfg.expected_hostname)
    monkeypatch.setattr(os, "geteuid", lambda: 10001)
    with pytest.raises(UpdateError) as e:
        installer.preflight()
    assert e.value.code == "forbidden" and not calls


def test_changed_package_is_rejected_before_start(installation):
    cfg, installer, calls, _ = installation
    from pathlib import Path

    Path(cfg.applications[0].image_archive.path).write_bytes(b"changed")
    with pytest.raises(UpdateError) as e:
        installer.apply()
    assert e.value.code == "artifact_mismatch" and not calls


def test_uncertain_start_is_recorded_and_never_replayed(installation):
    cfg, installer, calls, _ = installation
    original = installer.command

    def uncertain(argv, **kwargs):
        if argv[1] == "run":
            raise OSError("private diagnostic that must not be exported")
        return original(argv, **kwargs)

    installer.command = uncertain
    with pytest.raises(OSError):
        installer.apply()
    record = Journal(cfg.state_directory).get("initial_install", cfg.applications[0].application_id)
    assert record["phase"] == "recovery_required" and record["step"] == "start"
    assert "private diagnostic" not in dumps(record).decode()
    previous = len(calls)
    with pytest.raises(UpdateError) as e:
        installer.apply()
    assert e.value.code == "recovery_required" and len(calls) == previous


def test_changed_input_between_effects_stops_before_container_start(installation):
    cfg, installer, calls, _ = installation
    from pathlib import Path

    original = installer._stage

    def change(app):
        original(app)
        Path(app.files[0].source.path).write_bytes(b"changed secret")

    installer._stage = change
    with pytest.raises(UpdateError) as e:
        installer.apply()
    assert e.value.code == "artifact_mismatch"
    assert not any(argv[1] == "run" for argv in calls)
    assert (
        Journal(cfg.state_directory).get("initial_install", cfg.applications[0].application_id)[
            "phase"
        ]
        == "recovery_required"
    )


def test_legacy_versions_and_external_writable_models_refused(installation):
    cfg, _, _, _ = installation
    obj = cfg.model_dump()
    obj["applications"][0]["release"] = "0.1.0"
    with pytest.raises(ValidationError):
        Configuration.model_validate(obj)
    obj = cfg.model_dump()
    obj["applications"][0]["mounts"][0]["read_only"] = False
    with pytest.raises(ValidationError):
        Configuration.model_validate(obj)


def test_symlink_or_exposed_secret_input_refused(tmp_path):
    from pathlib import Path

    ref = local_file(tmp_path / "secret", b"secret", True)
    Path(ref["path"]).chmod(0o644)
    with pytest.raises(UpdateError):
        File.model_validate(ref).verify()
    link = tmp_path / "link"
    link.symlink_to(ref["path"])
    with pytest.raises(UpdateError):
        File(path=str(link), digest=ref["digest"]).verify()


def test_environment_is_literal_and_duplicate_free():
    assert environment(b"VALUE=$(no_shell_interpolation)\n")["VALUE"] == "$(no_shell_interpolation)"
    with pytest.raises(UpdateError):
        environment(b"A=1\nA=2\n")


def test_runtime_environment_cannot_be_replaced_by_application_user(installation):
    cfg, _, _, _ = installation
    obj = cfg.model_dump()
    obj["applications"][0]["directories"][0]["uid"] = 10001
    with pytest.raises(ValidationError):
        Configuration.model_validate(obj)


def test_docker_uses_local_socket_even_with_another_selected_context(monkeypatch):
    from types import SimpleNamespace

    from flamoris_updater_adapters.install import run

    calls = []

    def execute(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return SimpleNamespace(stdout=b"local-result")

    monkeypatch.setattr("subprocess.run", execute)
    monkeypatch.setenv("DOCKER_HOST", "tcp://unrelated.example.invalid:2376")
    assert run(["/usr/bin/docker", "info"]) == b"local-result"
    assert calls[0][0] == ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "info"]
    assert "DOCKER_HOST" not in calls[0][1]


def test_real_database_creation_is_scoped_to_new_database(tmp_path):
    dsn = os.getenv("FLAMORIS_INSTALL_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("Disposable PostgreSQL integration runs in CI")
    from types import SimpleNamespace

    import psycopg

    from flamoris_updater_adapters.install import Database

    admin = local_file(tmp_path / "admin", dsn.encode(), True)
    sql = local_file(
        tmp_path / "schema.sql",
        b"CREATE TABLE public.initial_data(id int); INSERT INTO public.initial_data VALUES (1);",
    )
    db = Database.model_validate(
        {
            "name": "initial_install_test",
            "admin_dsn": admin,
            "owner": "initial_install_owner",
            "runtime_role": "initial_install_runtime",
            "owner_password": local_file(tmp_path / "owner-pass", b"owner test password", True),
            "runtime_password": local_file(tmp_path / "app-pass", b"runtime test password", True),
            "sql_files": [sql],
        }
    )
    app = SimpleNamespace(application_id="flamoris-studio", database=db)
    installer = Installer.__new__(Installer)
    installer.connect = Installer._connect
    try:
        installer._database_preflight(app)
        installer._database_create(app)
        with psycopg.connect(dsn, dbname=db.name) as conn:
            assert conn.execute("SELECT id FROM public.initial_data").fetchall() == [(1,)]
            assert conn.execute(
                "SELECT has_table_privilege(%s,'public.initial_data','SELECT')", (db.runtime_role,)
            ).fetchone()[0]
        with pytest.raises(UpdateError) as e:
            installer._database_preflight(app)
        assert e.value.code == "not_empty"
    finally:
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("DROP DATABASE IF EXISTS initial_install_test WITH (FORCE)")
            conn.execute("DROP ROLE IF EXISTS initial_install_runtime")
            conn.execute("DROP ROLE IF EXISTS initial_install_owner")


def test_real_docker_candidate_can_be_installed_and_become_ready(tmp_path):
    candidate = os.getenv("FLAMORIS_INSTALL_TEST_DOCKER_CANDIDATE")
    if not candidate:
        pytest.skip("Disposable Docker integration runs in CI")
    import shutil
    import subprocess
    from pathlib import Path

    candidate = Path(candidate)
    metadata = json.loads((candidate / "candidate.json").read_text())
    archive = tmp_path / "image.tar"
    shutil.copyfile(candidate / "image.tar", archive)
    env = local_file(
        tmp_path / "input.env",
        b"FLAMORIS_HTTP_HOST=127.0.0.1\nFLAMORIS_HTTP_PORT=18765\n",
        True,
    )
    roots = {name: tmp_path / name for name in ("config", "workflows", "outputs")}
    container = "flamoris-initial-install-ci"
    cfg = Configuration.model_validate(
        {
            "install_profile_version": 1,
            "expected_hostname": socket.gethostname(),
            "platform": "linux/amd64",
            "state_directory": str(tmp_path / "history"),
            "applications": [
                {
                    "kind": "docker",
                    "application_id": "flamoris-generation-mcp",
                    "release": "1.0.0",
                    "image_archive": {
                        "path": str(archive),
                        "digest": metadata["files"]["image.tar"],
                    },
                    "image_id": metadata["image_id"],
                    "container_name": container,
                    "environment_file": str(roots["config"] / ".env"),
                    "directories": [
                        {
                            "path": str(root),
                            "uid": 0 if name == "config" else 10001,
                            "gid": 0 if name == "config" else 10001,
                        }
                        for name, root in roots.items()
                    ],
                    "files": [{"source": env, "destination": str(roots["config"] / ".env")}],
                    "mounts": [
                        {"source": str(roots[name]), "target": "/data/" + name, "read_only": False}
                        for name in ("workflows", "outputs")
                    ],
                    "health_url": "http://127.0.0.1:18765/healthz",
                }
            ],
        }
    )
    try:
        installer = Installer(cfg)
        assert installer.apply(start=False)["phase"] == "awaiting_setup"
        stopped = json.loads(subprocess.check_output(["/usr/bin/docker", "inspect", container]))[0]
        assert stopped["State"]["Running"] is False
        subprocess.check_call(["/usr/bin/docker", "start", container])
        installer.health(cfg.applications[0])
        installer._verify_running(cfg.applications[0])
    finally:
        subprocess.run(
            ["/usr/bin/docker", "rm", "-f", container],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
