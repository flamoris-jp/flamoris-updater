"""Release assembly verifies bytes and identity before publishing assets."""

import hashlib
import importlib.util
import io
import json
import tarfile
from pathlib import Path

import pytest

from flamoris_update_core.wire import digest, dumps, loads

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_distribution.py"
spec = importlib.util.spec_from_file_location("package_distribution", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def distribution(tmp_path):
    inputs = tmp_path / "inputs"
    inputs.mkdir()
    for arch in ("amd64", "arm64"):
        metadata = dumps({"compatibility_version": 1})
        index = dumps(
            {
                "content_index_version": 1,
                "platform": "linux/" + arch,
                "python": "3.12",
                "files": [
                    {
                        "path": "bundle-compatibility.json",
                        "digest": digest(metadata),
                        "size": len(metadata),
                        "executable": False,
                    }
                ],
            }
        )
        name = "flamoris-updater-1.0.2-linux-" + arch + ".tar.gz"
        with tarfile.open(inputs / name, "w:gz") as archive:
            for filename, raw in (
                ("bundle-compatibility.json", metadata),
                ("content-index.json", index),
            ):
                member = tarfile.TarInfo(filename)
                member.size, member.mode = len(raw), 0o444
                archive.addfile(member, io.BytesIO(raw))
        summary = {
            "artifact": name,
            "version": "1.0.2",
            "python": "3.12",
            "platform": "linux/" + arch,
            "digest": digest((inputs / name).read_bytes()),
            "content_index_digest": digest(index),
            "expanded_bytes": len(index) + len(metadata),
            "files": 2,
        }
        (inputs / ("bundle-digests-linux-" + arch + ".json")).write_bytes(dumps(summary))
    for filename in (
        "flamoris_updater-1.0.2-py3-none-any.whl",
        "flamoris_updater-1.0.2.tar.gz",
        "flamoris_update_core-1.0.0-py3-none-any.whl",
        "flamoris_update_core-1.0.0.tar.gz",
        "flamoris-updater-1.0.2-schemas.zip",
    ):
        (inputs / filename).write_bytes(b"CI-built-source-placeholder")
    return inputs, tmp_path / "output", SCRIPT.parent.parent


def test_complete_distribution_has_exact_source_checksums_and_both_platforms(distribution):
    inputs, output, root = distribution
    result = module.assemble(inputs, output, "1.0.2", "a" * 40, root)
    assert result["source"]["revision"] == "a" * 40
    assert result["source"]["tag"] == "v1.0.2"
    assert {b["platform"] for b in result["bundles"]} == {"linux/amd64", "linux/arm64"}
    assert result["live_acceptance"] is False
    files = list(output.iterdir())
    assert len(files) == 14
    checksums = (output / "SHA256SUMS").read_text().splitlines()
    assert len(checksums) == 13
    for line in checksums:
        expected, filename = line.split("  ")
        assert hashlib.sha256((output / filename).read_bytes()).hexdigest() == expected
    assert loads((output / "distribution.json").read_bytes()) == result
    with pytest.raises(ValueError, match="overwrite"):
        module.assemble(inputs, output, "1.0.2", "a" * 40, root)


@pytest.mark.parametrize("fault", ["version", "digest", "platform", "missing", "extra"])
def test_invalid_candidate_never_creates_distribution(distribution, fault):
    inputs, output, root = distribution
    summary_path = inputs / "bundle-digests-linux-amd64.json"
    summary = json.loads(summary_path.read_bytes())
    if fault == "version":
        summary["version"] = "1.1.0"
    if fault == "platform":
        summary["platform"] = "linux/arm64"
    if fault == "digest":
        (inputs / summary["artifact"]).write_bytes(b"modified-candidate")
    if fault == "missing":
        (inputs / "flamoris-updater-1.0.2-schemas.zip").unlink()
    if fault == "extra":
        (inputs / "unexpected-private-file").write_bytes(b"must-not-publish")
    summary_path.write_text(json.dumps(summary))
    with pytest.raises(ValueError):
        module.assemble(inputs, output, "1.0.2", "a" * 40, root)
    assert not output.exists()


def test_revision_and_package_version_must_be_explicit(distribution):
    inputs, output, root = distribution
    with pytest.raises(ValueError, match="exact source"):
        module.assemble(inputs, output, "1.0.2", "main", root)
    with pytest.raises(ValueError, match="versions disagree"):
        module.assemble(inputs, output, "1.1.0", "a" * 40, root)
    assert not output.exists()
