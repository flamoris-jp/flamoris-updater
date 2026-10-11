"""Disposable CI acceptance of a repository-owned published Generation image."""

import json
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
        finally:
            names = run(["/usr/bin/docker", "container", "ls", "--all", "--format", "{{.Names}}"])
            if "flamoris-generation-mcp" in names.decode().splitlines():
                run(["/usr/bin/docker", "container", "rm", "--force", "flamoris-generation-mcp"])


if __name__ == "__main__":
    main()
