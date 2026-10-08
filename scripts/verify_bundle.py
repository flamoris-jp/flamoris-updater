"""Stage the generated archive using the shipping verifier and exercise indexed entrypoints."""

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from flamoris_update_core.models import Artifact
from flamoris_update_core.wire import loads
from flamoris_updater_adapters.artifacts import NativeStore


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
        assert (stage / "site-packages/flamoris_updater_adapters/static/app.js").is_file()
        assert (stage / "site-packages/flamoris_updater_adapters/compatibility.py").is_file()
    print("Verified indexed native bundle and all installed entrypoints")


if __name__ == "__main__":
    main()
