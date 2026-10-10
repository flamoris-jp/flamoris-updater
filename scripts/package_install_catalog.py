"""Validate the complete initial candidate matrix and assemble flat HTTPS assets."""

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from build_initial_candidate import SOURCES

from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.artifacts import origin
from flamoris_updater_adapters.install import VERSIONS
from flamoris_updater_adapters.recipes import build_catalog

PLATFORMS = ("linux/amd64", "linux/arm64")


def file_digest(filename):
    h = hashlib.sha256()
    with filename.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def assemble(candidates, output, *, base_url):
    origin(base_url)
    parsed = urlsplit(base_url)
    if (
        parsed.query
        or any(part in (".", "..") for part in unquote(parsed.path).split("/"))
        or "\\" in base_url
        or any(c.isspace() or ord(c) < 32 for c in base_url)
    ):
        raise ValueError("A direct HTTPS directory without query or traversal is required")
    if candidates.is_symlink():
        raise ValueError("Candidate symlinks are forbidden")
    candidates = candidates.resolve(strict=True)
    if not candidates.is_dir():
        raise ValueError("A candidate artifact directory is required")
    if output.exists() or output.is_symlink():
        raise ValueError("Distribution output already exists")
    output = output.resolve()
    if output.is_relative_to(candidates) or candidates.is_relative_to(output):
        raise ValueError("Distribution must be separate from candidate inputs")

    expected = {(app, VERSIONS[app], platform) for app in SOURCES for platform in PLATFORMS}
    actual = set()
    prepared = []
    for directory in sorted(candidates.iterdir()):
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Each candidate artifact must be a directory")
        members = list(directory.rglob("*"))
        if any(p.is_symlink() or not (p.is_file() or p.is_dir()) for p in members):
            raise ValueError("Candidate symlinks and special files are forbidden")
        metadata = loads((directory / "candidate.json").read_bytes())
        fields = {
            "application_id",
            "release",
            "source_revision",
            "compatible_from",
            "platform",
            "published",
            "files",
        }
        if metadata.get("application_id") != "flamoris-gpu-node-manager":
            fields.add("image_id")
        if set(metadata) != fields:
            raise ValueError("Unexpected candidate metadata fields")
        identity = (metadata["application_id"], metadata["release"], metadata["platform"])
        if identity not in expected or identity in actual:
            raise ValueError("Unexpected or duplicate initial candidate identity")
        if (
            metadata.get("published") is not False
            or metadata.get("source_revision") != SOURCES[identity[0]]
            or metadata.get("compatible_from") != []
        ):
            raise ValueError("Candidate must bind the reviewed initial source")
        files = metadata["files"]
        if not isinstance(files, dict) or not files:
            raise ValueError("Candidate files are required")
        for name, digest in files.items():
            path = PurePosixPath(name)
            if (
                not name
                or path.is_absolute()
                or any(part in (".", "..") for part in name.split("/"))
                or str(path) != name
                or "\\" in name
                or any(c in name for c in "\r\n\0")
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            ):
                raise ValueError("Invalid candidate member or digest")
        found = {p.relative_to(directory).as_posix() for p in members if p.is_file()}
        if found != {"candidate.json", *files} or "candidate.json" in files:
            raise ValueError("Candidate has missing or unexpected files")
        for name, expected_digest in files.items():
            if (directory / name).stat().st_size > 4 * 1024**3:
                raise ValueError("Candidate exceeds the managed download limit")
            if file_digest(directory / name) != expected_digest:
                raise ValueError("Candidate file digest mismatch")
        actual.add(identity)
        prepared.append((metadata, directory))
    if actual != expected:
        raise ValueError("All six applications on both platforms are required")

    location = base_url.rstrip("/")
    catalog = build_catalog([(metadata, location) for metadata, _ in prepared])
    catalog_data = loads(dumps(catalog))
    assets = []
    releases = []
    used_names = {"catalog.json", "application-distribution.json", "SHA256SUMS"}
    for (metadata, directory), recipe in zip(prepared, catalog_data["recipes"], strict=True):
        prefix = "-".join(
            (metadata["application_id"], metadata["release"], metadata["platform"].split("/")[1])
        )
        mapping = {}
        for name, expected_digest in sorted(metadata["files"].items()):
            # The local package key stays unchanged, including wheel and SQL filenames.
            # Only the public flat asset name is changed to avoid cross-app collisions.
            path_id = hashlib.sha256(name.encode()).hexdigest()[:16]
            asset = f"{prefix}-{path_id}-{PurePosixPath(name).name}"
            if not re.fullmatch(r"[A-Za-z0-9_.+-]+", asset) or asset in used_names:
                raise ValueError("Unsupported or duplicate release asset name")
            used_names.add(asset)
            url = location + "/" + asset
            recipe["downloads"][name]["url"] = url
            assets.append((directory / name, asset, expected_digest))
            mapping[name] = {"asset": asset, "url": url, "digest": expected_digest}
        releases.append({**metadata, "published": False, "assets": mapping})
    # Re-validate the complete catalog after rebinding URLs.
    catalog = type(catalog).model_validate(loads(dumps(catalog_data)))
    output.mkdir(parents=True, exist_ok=False)
    for source, name, expected_digest in assets:
        shutil.copyfile(source, output / name)
        if file_digest(output / name) != expected_digest:
            raise ValueError("Copied asset digest mismatch; retain partial output for inspection")
    (output / "catalog.json").write_bytes(dumps(catalog) + b"\n")
    (output / "application-distribution.json").write_text(
        json.dumps(
            {"catalog": location + "/catalog.json", "published": False, "releases": releases},
            indent=2,
        )
        + "\n"
    )
    checksums = [
        file_digest(p).removeprefix("sha256:") + "  " + p.name for p in sorted(output.iterdir())
    ]
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n")
    return catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    args = parser.parse_args()
    assemble(args.candidates, args.output, base_url=args.base_url)


if __name__ == "__main__":
    main()
