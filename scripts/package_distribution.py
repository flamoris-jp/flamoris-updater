"""Assemble a verified initial-install distribution; not a signed Core catalog."""

import argparse
import hashlib
import re
import shutil
import tempfile
import tomllib
from pathlib import Path

from flamoris_update_core.models import Artifact
from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.artifacts import NativeStore, relative


def checksum(path):
    with path.open("rb") as stream:
        return "sha256:" + hashlib.file_digest(stream, "sha256").hexdigest()


def assemble(inputs, output, release, revision, root):
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("An exact source revision is required")
    package = tomllib.loads((root / "pyproject.toml").read_text())["project"]
    if release != "1.0.0" or package["version"] != release:
        raise ValueError("Distribution and package versions disagree")
    notes = (root / "release-notes" / (release + ".md")).read_bytes()
    changes = (root / "release-notes" / (release + ".changes.json")).read_bytes()
    if loads(changes)["release"] != release:
        raise ValueError("Release notes version disagrees")
    summaries = [loads(p.read_bytes()) for p in inputs.rglob("bundle-digests-linux-*.json")]
    if len(summaries) != 2 or {s["platform"] for s in summaries} != {"linux/amd64", "linux/arm64"}:
        raise ValueError("Both verified platform bundles are required")
    candidates = sorted(p for p in inputs.rglob("*") if p.is_file())
    names = [p.name for p in candidates]
    if len(set(names)) != len(names) or any(p.is_symlink() for p in candidates):
        raise ValueError("Duplicate or linked distribution asset")
    # Resolve only exact flat names from the trusted build artifact directory.
    paths = {p.name: p for p in candidates}
    for summary in summaries:
        name = relative(summary["artifact"])
        if "/" in name or summary["version"] != release or summary["python"] != "3.12":
            raise ValueError("Unexpected bundle identity")
        archive = paths[name]
        if checksum(archive) != summary["digest"]:
            raise ValueError("Bundle digest mismatch")

        class LocalArtifact:
            def chunks(self, _url, limit):
                if archive.stat().st_size > limit:
                    raise ValueError("Download budget")
                with archive.open("rb") as stream:
                    yield from iter(lambda: stream.read(65536), b"")

        artifact = Artifact(
            kind="native",
            platform=summary["platform"],
            locator="https://build.example.invalid/" + name,
            digest=summary["digest"],
            content_index_digest=summary["content_index_digest"],
            max_expanded_bytes=summary["expanded_bytes"],
        )
        # Both architectures can be checked statically here. Running entrypoints
        # happened on their native runners, before artifact upload.
        with tempfile.TemporaryDirectory() as temporary:
            store = NativeStore(
                Path(temporary) / "verified",
                LocalArtifact(),
                max_download=archive.stat().st_size,
                max_expanded=summary["expanded_bytes"],
                max_files=summary["files"],
                reserve=1024,
            )
            stage = store.prepare(artifact)
            store.verify(stage, artifact)
    required = {
        "flamoris_updater-1.0.0-py3-none-any.whl",
        "flamoris_updater-1.0.0.tar.gz",
        "flamoris_update_core-1.0.0-py3-none-any.whl",
        "flamoris_update_core-1.0.0.tar.gz",
        "flamoris-updater-1.0.0-schemas.zip",
    }
    expected = required | {
        "flamoris-updater-1.0.0-linux-amd64.tar.gz",
        "flamoris-updater-1.0.0-linux-arm64.tar.gz",
        "bundle-digests-linux-amd64.json",
        "bundle-digests-linux-arm64.json",
    }
    if set(paths) != expected:
        raise ValueError(
            "Source/SDK/schema distribution is incomplete or contains unexpected assets"
        )
    if output.exists():
        raise ValueError("Refusing to overwrite assembled distribution")
    output.mkdir(parents=True)
    for p in candidates:
        shutil.copyfile(p, output / p.name)
    (output / "release-notes.md").write_bytes(notes)
    (output / "changes.json").write_bytes(changes)
    shutil.copyfile(root / "docs/DISTRIBUTION.md", output / "INSTALL-v1.0.0.md")
    metadata = {
        "distribution_version": 1,
        "application_id": "flamoris-updater",
        "release": release,
        "source": {
            "repository": "flamoris-jp/flamoris-updater",
            "tag": "v" + release,
            "revision": revision,
        },
        "bundles": sorted(summaries, key=lambda s: s["platform"]),
        "trust": "GitHub HTTPS release; SHA-256 integrity and indexed files; not a signed Core catalog",
        "live_acceptance": False,
    }
    (output / "distribution.json").write_bytes(dumps(metadata) + b"\n")
    assets = sorted(output.iterdir())
    (output / "SHA256SUMS").write_text(
        "".join(checksum(p).removeprefix("sha256:") + "  " + p.name + "\n" for p in assets)
    )
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inputs", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    args = parser.parse_args()
    metadata = assemble(
        args.inputs,
        args.output,
        args.version,
        args.revision,
        Path(__file__).resolve().parent.parent,
    )
    print(dumps(metadata).decode())


if __name__ == "__main__":
    main()
