"""A catalog must bind the complete reviewed matrix to the actual release bytes."""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from flamoris_update_core.wire import digest, dumps, loads
from flamoris_updater_adapters.install import VERSIONS
from flamoris_updater_adapters.managed import Catalog, Manager

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/package_install_catalog.py"
spec = importlib.util.spec_from_file_location("package_install_catalog", SCRIPT)
module = importlib.util.module_from_spec(spec)
with patch.object(sys, "path", [str(SCRIPT.parent), *sys.path]):
    spec.loader.exec_module(module)
BASE = "https://releases.example.invalid/initial-apps"


@pytest.fixture
def inputs(tmp_path):
    candidates = tmp_path / "candidates"
    candidates.mkdir()
    for app, revision in module.SOURCES.items():
        for platform in module.PLATFORMS:
            directory = candidates / (app + "-" + platform.split("/")[1])
            directory.mkdir()
            payloads = {"image.tar": (app + platform).encode()}
            if app == "flamoris-gpu-node-manager":
                payloads = {"manager.whl": (app + platform).encode(), "dependency.whl": b"wheel"}
            if app == "flamoris-ai-agent":
                payloads["db/01_schema.sql"] = b"schema"
                payloads["db/migrations/001.sql"] = b"migration"
            for name, raw in payloads.items():
                filename = directory / name
                filename.parent.mkdir(parents=True, exist_ok=True)
                filename.write_bytes(raw)
            metadata = {
                "application_id": app,
                "release": VERSIONS[app],
                "source_revision": revision,
                "platform": platform,
                "published": False,
                "compatible_from": [],
                "files": {name: digest(raw) for name, raw in payloads.items()},
            }
            if app != "flamoris-gpu-node-manager":
                metadata["image_id"] = digest(b"image-id")
            (directory / "candidate.json").write_bytes(dumps(metadata))
    return candidates, tmp_path / "distribution"


def test_complete_flat_distribution_keeps_package_keys_and_binds_actual_bytes(inputs, tmp_path):
    candidates, output = inputs
    catalog = module.assemble(candidates, output, base_url=BASE + "/")
    assert len(catalog.recipes) == 12
    assert {r.platform for r in catalog.recipes} == set(module.PLATFORMS)
    assert Catalog.model_validate(loads((output / "catalog.json").read_bytes())) == catalog
    manifest = loads((output / "application-distribution.json").read_bytes())
    assert manifest["published"] is False
    assert manifest["catalog"] == BASE + "/catalog.json"
    assert len(manifest["releases"]) == 12
    names = []
    for recipe in catalog.recipes:
        for package_key, item in recipe.downloads.items():
            name = item.url.removeprefix(BASE + "/")
            assert "/" not in name
            assert module.file_digest(output / name) == item.digest
            names.append(name)
            if recipe.application_id == "flamoris-ai-agent":
                assert "db/01_schema.sql" in recipe.downloads
            if recipe.application_id == "flamoris-gpu-node-manager":
                assert package_key.endswith(".whl")
    assert len(names) == len(set(names))
    checksums = (output / "SHA256SUMS").read_text().splitlines()
    assert len(checksums) == len(list(output.iterdir())) - 1
    for line in checksums:
        expected, name = line.split("  ")
        assert module.file_digest(output / name) == "sha256:" + expected

    # The installed 1.0.1 manager accepts the assembled schema unchanged.
    def serve(request):
        filename = request.url.path.rsplit("/", 1)[-1]
        return httpx.Response(200, content=(output / filename).read_bytes())

    client = httpx.Client(transport=httpx.MockTransport(serve), follow_redirects=False)
    manager = Manager(tmp_path / "state", tmp_path / "apps", client=client)
    assert manager.configure(BASE + "/catalog.json") == {"configured": True}
    assert manager.catalog() == catalog
    for recipe in catalog.recipes:
        for key, item in recipe.downloads.items():
            saved = tmp_path / "downloads" / recipe.application_id / recipe.platform / key
            saved.parent.mkdir(parents=True, exist_ok=True)
            manager._download(item.url, 4 * 1024**3, saved, item.digest)
            assert module.file_digest(saved) == item.digest
    assert all(not s.default for r in catalog.recipes for s in r.settings if s.secret)


@pytest.mark.parametrize(
    "fault",
    [
        "missing_matrix",
        "duplicate",
        "version",
        "revision",
        "platform",
        "published",
        "compatibility",
        "digest",
        "missing_file",
        "extra_file",
        "extra_metadata",
        "traversal",
        "symlink",
        "directory_symlink",
    ],
)
def test_incomplete_tampered_or_unsafe_candidates_stop_before_output(inputs, fault):
    candidates, output = inputs
    directory = candidates / "flamoris-generation-mcp-amd64"
    filename = directory / "candidate.json"
    metadata = loads(filename.read_bytes())
    if fault == "missing_matrix":
        filename.unlink()
    elif fault == "duplicate":
        import shutil

        shutil.copytree(directory, candidates / "duplicate")
    elif fault in {"version", "revision", "platform", "published", "compatibility", "traversal"}:
        if fault == "version":
            metadata["release"] = "1.0.1"
        elif fault == "revision":
            metadata["source_revision"] = "a" * 40
        elif fault == "platform":
            metadata["platform"] = "windows/amd64"
        elif fault == "published":
            metadata["published"] = True
        elif fault == "compatibility":
            metadata["compatible_from"] = ["0.9.0"]
        else:
            metadata["files"]["../outside"] = digest(b"outside")
        filename.write_text(json.dumps(metadata))
    elif fault == "digest":
        (directory / "image.tar").write_bytes(b"tampered")
    elif fault == "missing_file":
        (directory / "image.tar").unlink()
    elif fault == "extra_file":
        (directory / "unlisted.key").write_bytes(b"not-for-publication")
    elif fault == "extra_metadata":
        metadata["operator_token"] = "not-for-publication"
        filename.write_text(json.dumps(metadata))
    elif fault == "symlink":
        (directory / "image.tar").unlink()
        (directory / "image.tar").symlink_to(filename)
    else:
        (candidates / "alias").symlink_to(directory, target_is_directory=True)
    with pytest.raises((ValueError, FileNotFoundError)):
        module.assemble(candidates, output, base_url=BASE)
    assert not output.exists()


def test_distribution_refuses_replacement_and_overlapping_inputs(inputs):
    candidates, output = inputs
    module.assemble(candidates, output, base_url=BASE)
    with pytest.raises(ValueError, match="already exists"):
        module.assemble(candidates, output, base_url=BASE)
    with pytest.raises(ValueError, match="separate"):
        module.assemble(candidates, candidates / "output", base_url=BASE)


@pytest.mark.parametrize("suffix", ["?token=secret", "/../escape", "/%2e%2e/escape"])
def test_catalog_origin_refuses_query_or_traversal(inputs, suffix):
    candidates, output = inputs
    with pytest.raises(ValueError):
        module.assemble(candidates, output, base_url=BASE + suffix)
    assert not output.exists()
