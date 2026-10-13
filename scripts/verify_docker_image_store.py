"""Disposable CI acceptance of a repository-owned published Generation image."""

import json
import os
import tempfile
from pathlib import Path

from flamoris_updater_adapters.install import run
from flamoris_updater_adapters.managed import Manager, Start


def main():
    with tempfile.TemporaryDirectory(prefix="flamoris-store-ci-") as directory:
        root = Path(directory)
        models = root / "models"
        models.mkdir()
        manager = Manager(root / "manager", root / "apps")
        manager.configure(
            "https://github.com/flamoris-jp/flamoris-generation-mcp/releases/download/v1.0.2/catalog.json"
        )
        job = manager.start(
            "install",
            Start(
                application_id="flamoris-generation-mcp",
                release="1.0.2",
                request_key="docker-image-store-ci",
                settings={
                    "PORT": "18765",
                    "MODEL_ROOT": str(models),
                    "COMFYUI_URL": "http://127.0.0.1:18188",
                },
            ),
        )
        try:
            manager.run_job(job["job_id"])
            job = manager.journal.get("managed_job", job["job_id"])
            assert job["phase"] == "awaiting_setup", job.get("failure")
            manager.start_setup("flamoris-generation-mcp")
            manager.complete("flamoris-generation-mcp")
            installed = manager.journal.get("managed_app", "flamoris-generation-mcp")
            observed = json.loads(
                run(
                    [
                        "/usr/bin/docker",
                        "container",
                        "inspect",
                        "--format",
                        "{{json .}}",
                        installed["profile"]["container_name"],
                    ]
                )
            )
            assert observed["Image"] == installed["profile"]["image_id"]
            assert observed["State"]["Running"] is True
            print("Published Generation 1.0.2: install, setup, health and runtime ID verified")
            manager.configure(
                "https://github.com/flamoris-jp/flamoris-generation-mcp/releases/download/v1.0.4/catalog.json"
            )
            upgrade = manager.start(
                "update",
                Start(
                    application_id="flamoris-generation-mcp",
                    release="1.0.4",
                    request_key="output-version-ci",
                ),
            )
            manager.run_job(upgrade["job_id"])
            outcome = manager.journal.get("managed_job", upgrade["job_id"])
            assert outcome["phase"] == "succeeded", {
                k: outcome.get(k) for k in ("phase", "step", "failure")
            }
            env = root / "apps/flamoris-generation-mcp/config/runtime.env"
            before = env.read_bytes()
            os.chmod(root, 0o755)
            media = root / "media"
            media.mkdir()
            os.chown(media, 10001, 1001)
            os.chmod(media, 0o2755)
            permissions = media.stat()
            configured = manager.invoke(
                "updater_outputs_configure",
                {
                    "application_id": "flamoris-generation-mcp",
                    "request_key": "output-directory-ci",
                    "directories": {"yue2": str(media)},
                },
            )
            manager.run_job(configured["job_id"])
            outcome = manager.journal.get("managed_job", configured["job_id"])
            assert outcome["phase"] == "succeeded", {
                k: outcome.get(k) for k in ("phase", "step", "failure")
            }
            run(
                [
                    "/usr/bin/docker",
                    "exec",
                    "flamoris-generation-mcp",
                    "python",
                    "-c",
                    "import os,pathlib; assert os.getuid()==10001; p=pathlib.Path('/data/music-output/test.txt'); p.write_text('operator-copy'); assert p.stat().st_gid==1001; assert os.environ['FLAMORIS_YUE2_OUTPUT_ROOT']=='/data/music-output'",
                ]
            )
            assert (media / "test.txt").read_text() == "operator-copy"
            assert env.read_bytes() == before
            assert (media.stat().st_uid, media.stat().st_gid, media.stat().st_mode) == (
                permissions.st_uid,
                permissions.st_gid,
                permissions.st_mode,
            )
            disabled = manager.invoke(
                "updater_outputs_configure",
                {
                    "application_id": "flamoris-generation-mcp",
                    "request_key": "disable-directory-ci",
                    "directories": {"yue2": ""},
                },
            )
            manager.run_job(disabled["job_id"])
            outcome = manager.journal.get("managed_job", disabled["job_id"])
            assert outcome["phase"] == "succeeded", {
                k: outcome.get(k) for k in ("phase", "step", "failure")
            }
            manager.delete_previous("flamoris-generation-mcp")
            assert (manager.state / "packages" / upgrade["job_id"]).exists()
            assert (media / "test.txt").read_text() == "operator-copy"
            assert env.read_bytes() == before
            print(
                "Published Generation 1.0.4: configure/disable, UID write, SGID and private settings preservation verified"
            )
            manager.configure(
                "https://github.com/flamoris-jp/flamoris-generation-mcp/releases/download/v1.0.6/catalog.json"
            )
            upgrade = manager.start(
                "update",
                Start(
                    application_id="flamoris-generation-mcp",
                    release="1.0.6",
                    request_key="reference-version-ci",
                ),
            )
            manager.run_job(upgrade["job_id"])
            assert manager.journal.get("managed_job", upgrade["job_id"])["phase"] == "succeeded"
            inputs = root / "comfy-input"
            inputs.mkdir()
            os.chown(inputs, 10001, 1001)
            os.chmod(inputs, 0o2755)
            configured = manager.invoke(
                "updater_outputs_configure",
                {
                    "application_id": "flamoris-generation-mcp",
                    "request_key": "reference-directory-ci",
                    "directories": {"comfyui": str(inputs)},
                },
            )
            manager.run_job(configured["job_id"])
            result = manager.journal.get("managed_job", configured["job_id"])
            assert result["phase"] == "succeeded", result.get("failure")
            run(
                [
                    "/usr/bin/docker",
                    "exec",
                    "flamoris-generation-mcp",
                    "python",
                    "-c",
                    "import os,pathlib; p=pathlib.Path('/data/comfyui-input/test.txt'); "
                    "p.write_text('reference-input'); "
                    "assert os.environ['FLAMORIS_COMFYUI_INPUT_ROOT']=='/data/comfyui-input'",
                ]
            )
            assert (inputs / "test.txt").read_text() == "reference-input"
            assert env.read_bytes() == before
            disabled = manager.invoke(
                "updater_outputs_configure",
                {
                    "application_id": "flamoris-generation-mcp",
                    "request_key": "disable-reference-ci",
                    "directories": {"comfyui": ""},
                },
            )
            manager.run_job(disabled["job_id"])
            assert manager.journal.get("managed_job", disabled["job_id"])["phase"] == "succeeded"
            assert (inputs / "test.txt").read_text() == "reference-input"
            assert (media / "test.txt").read_text() == "operator-copy"
            assert env.read_bytes() == before
            print("Published Generation 1.0.6: shared input bind/write/disable verified")
        finally:
            names = run(["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"])
            if "flamoris-generation-mcp" in names.decode().splitlines():
                run(["/usr/bin/docker", "container", "rm", "--force", "flamoris-generation-mcp"])


if __name__ == "__main__":
    main()
