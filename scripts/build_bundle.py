"""Build an immutable native bundle in CI/workstations; hosts only stage this result."""

import argparse
import gzip
import hashlib
import importlib.metadata
import json
import platform
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

ENTRYPOINTS = {
    "flamoris-updater": "flamoris_updater_adapters.cli",
    "flamoris-updater-helper": "flamoris_updater_adapters.helper",
    "flamoris-updater-host": "flamoris_updater_adapters.host_api",
    "flamoris-updater-recovery": "flamoris_updater_adapters.recovery_cli",
    "flamoris-update-migration": "flamoris_update_migration.runner",
}


def encoded(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def build(wheelhouse, output, target, version, interpreter):
    actual = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}.get(platform.machine())
    if sys.version_info[:2] != (3, 12) or actual != target or not Path(interpreter).is_absolute():
        raise ValueError(
            "Build on target architecture with Python 3.12 and an explicit host interpreter path"
        )
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="updater-bundle-") as temporary:
        root = Path(temporary)
        vendor = root / "site-packages"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--only-binary=:all:",
                "--no-index",
                "--find-links",
                str(Path(wheelhouse).absolute()),
                "--no-compile",
                "--target",
                str(vendor),
                "flamoris-updater==" + version,
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        # Installed console scripts contain build-machine paths; replace them with fixed bundle launchers.
        import shutil

        shutil.rmtree(vendor / "bin", ignore_errors=True)
        shutil.rmtree(root / "bin", ignore_errors=True)
        (root / "bin").mkdir()
        for name, module in ENTRYPOINTS.items():
            launcher = (
                f"#!{interpreter} -I\nimport sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(__file__).resolve().parent.parent/'site-packages'))\nfrom {module} import main\nmain()\n"
            ).encode()
            path = root / "bin" / name
            path.write_bytes(launcher)
            path.chmod(0o555)
        metadata = {
            "compatibility_version": 1,
            "journal_version": 1,
            "control_store_version": 1,
            "recovery_protocol_version": 1,
            "package": "flamoris-updater",
            "version": version,
        }
        (root / "bundle-compatibility.json").write_bytes(encoded(metadata))
        dependencies = []
        for distribution in importlib.metadata.distributions(path=[str(vendor)]):
            dependencies.append(
                {
                    "name": distribution.metadata["Name"],
                    "version": distribution.version,
                    "license": distribution.metadata.get("License-Expression")
                    or distribution.metadata.get("License")
                    or "See bundled dist-info licenses",
                }
            )
        (root / "dependencies.json").write_bytes(
            encoded(
                {
                    "format_version": 1,
                    "packages": sorted(dependencies, key=lambda x: x["name"].lower()),
                }
            )
        )
        files = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ValueError("Bundle must contain only regular files")
            if path.is_file():
                raw = path.read_bytes()
                executable = bool(path.stat().st_mode & 0o111)
                path.chmod(0o555 if executable else 0o444)
                files.append(
                    {
                        "path": str(path.relative_to(root)),
                        "digest": sha(raw),
                        "size": len(raw),
                        "executable": executable,
                    }
                )
        index = encoded(
            {"content_index_version": 1, "platform": target, "python": "3.12", "files": files}
        )
        if len(index) > 1024 * 1024:
            raise ValueError("Content index exceeds v1 budget")
        (root / "content-index.json").write_bytes(index)
        destination = output / (
            "flamoris-updater-" + version + "-" + target.replace("/", "-") + ".tar.gz"
        )
        with (
            destination.open("wb") as outgoing,
            gzip.GzipFile(fileobj=outgoing, mode="wb", filename="", mtime=0) as compressed,
            tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive,
        ):
            for path in sorted(root.rglob("*")):
                if path.is_file():
                    info = archive.gettarinfo(str(path), str(path.relative_to(root)))
                    info.uid = info.gid = 0
                    info.uname = info.gname = ""
                    info.mtime = 0
                    info.mode = 0o555 if path.stat().st_mode & 0o111 else 0o444
                    with path.open("rb") as stream:
                        archive.addfile(info, stream)
        summary = {
            "platform": target,
            "python": "3.12",
            "artifact": destination.name,
            "digest": sha(destination.read_bytes()),
            "content_index_digest": sha(index),
            "expanded_bytes": sum(x["size"] for x in files) + len(index),
            "files": len(files) + 1,
        }
        (output / "bundle-digests.json").write_bytes(encoded(summary))
        return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wheelhouse", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--platform", choices=["linux/amd64", "linux/arm64"], required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--python-executable", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            build(
                args.wheelhouse, args.output, args.platform, args.version, args.python_executable
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
