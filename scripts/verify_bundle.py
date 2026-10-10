"""Stage the generated archive using the shipping verifier and exercise indexed entrypoints."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from flamoris_update_core.models import Artifact
from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.artifacts import NativeStore
from flamoris_updater_adapters.setup import BootstrapConfig


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True)
    args = parser.parse_args()
    output = Path(args.directory)
    summary = loads((output / "bundle-digests.json").read_bytes())
    archive = output / summary["artifact"]

    class LocalBuildArtifact:
        def chunks(self, url, limit):
            with archive.open("rb") as stream:
                total = 0
                for part in iter(lambda: stream.read(65536), b""):
                    total += len(part)
                    if total > limit:
                        raise ValueError("quota")
                    yield part

    artifact = Artifact(
        kind="native",
        platform=summary["platform"],
        locator="https://build.example.invalid/" + summary["artifact"],
        digest=summary["digest"],
        content_index_digest=summary["content_index_digest"],
        max_expanded_bytes=summary["expanded_bytes"],
    )
    with tempfile.TemporaryDirectory() as temporary:
        store = NativeStore(
            Path(temporary) / "staged",
            LocalBuildArtifact(),
            max_download=archive.stat().st_size,
            max_expanded=summary["expanded_bytes"],
            max_files=summary["files"],
            reserve=1024,
        )
        stage = store.prepare(artifact)
        store.verify(stage, artifact)
        for entry in (stage / "bin").iterdir():
            subprocess.run(
                [sys.executable, "-I", str(entry), "--help"], check=True, stdout=subprocess.DEVNULL
            )
        # Module imports and static assets must be present inside the actual bundle.
        assert (stage / "site-packages/flamoris_updater_adapters/static/managed.js").is_file()
        assert (stage / "site-packages/flamoris_updater_adapters/compatibility.py").is_file()
        cfg = BootstrapConfig(
            state_directory=temporary + "/web",
            helper_state_directory=temporary + "/manager",
            root=temporary + "/apps",
            socket_path=temporary + "/ipc/manager.sock",
            service_uid=10002,
            service_gid=10002,
            public_origin="http://127.0.0.1:8764",
        )
        config = Path(temporary) / "setup.json"
        config.write_bytes(dumps(cfg))
        config.chmod(0o600)
        identity = loads(
            subprocess.check_output(
                [
                    sys.executable,
                    "-I",
                    str(stage / "bin/flamoris-updater-service"),
                    "check",
                    "--config",
                    str(config),
                ]
            )
        )
        assert identity == dict(
            version=summary["version"],
            supervisor_protocol_version=1,
            integration_auth_version=1,
            runtime_root=str(stage / "site-packages"),
        )
        # Execution must retain the exact index, including privileged launchers.
        store.verify(stage, artifact)
    print("Verified indexed native bundle, all entrypoints and unchanged content after execution")


if __name__ == "__main__":
    main()
