"""Build reviewable initial-install candidates in CI, never on production hosts."""

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

SOURCES = {
    "flamoris-ai-agent": "8ac1e9555355a5cbb255e8939f43ad041a0d221c",
    "flamoris-studio": "eec497cc0dd2e044db1963f22d928fca84a08859",
    "flamoris-intelligence-mcp": "f791bf236342e7c831e4d0291709bacb2f0e54bc",
    "flamoris-generation-mcp": "7e2b53227b68745a520c3fd5d20f366b16b66057",
    "flamoris-mcp-hub": "623f6329d94e168b75c0bcb9e7d8be03345d5a76",
    "flamoris-gpu-node-manager": "2ca548dc8040bbda87074dba0460b50e1adb443e",
}


def run(argv):
    return subprocess.check_output(argv, text=True).strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--application", choices=SOURCES, required=True)
    parser.add_argument("--platform", choices=["linux/amd64", "linux/arm64"], required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    app = args.application
    version = "1.2.0" if app == "flamoris-gpu-node-manager" else "1.0.0"
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    source = output.parent / (app + "-source")
    run(["git", "init", str(source)])
    run(
        [
            "git",
            "-C",
            str(source),
            "fetch",
            "--depth=1",
            f"https://github.com/flamoris-jp/{app}.git",
            SOURCES[app],
        ]
    )
    run(["git", "-C", str(source), "checkout", "--detach", "FETCH_HEAD"])
    import tomllib

    project = tomllib.loads((source / "pyproject.toml").read_text())["project"]
    if project["version"] != version or project["name"] != app:
        raise SystemExit("Pinned source package identity mismatch")
    metadata = {
        "application_id": app,
        "release": version,
        "source_revision": SOURCES[app],
        "platform": args.platform,
        "published": False,
    }
    if app == "flamoris-gpu-node-manager":
        import sys

        run([sys.executable, "-m", "pip", "wheel", "--wheel-dir", str(output), str(source)])
    else:
        tag = f"initial-candidate/{app}:{version}"
        command = [
            "docker",
            "build",
            "--platform",
            args.platform,
            "--tag",
            tag,
            "--label",
            f"org.opencontainers.image.title={app}",
            "--label",
            f"org.opencontainers.image.version={version}",
            "--label",
            f"org.opencontainers.image.revision={SOURCES[app]}",
        ]
        if app == "flamoris-generation-mcp":
            command += [
                "--label",
                'net.flamoris.components={"flamoris-generation-controller":"1.0.0"}',
            ]
        run([*command, str(source)])
        image = json.loads(run(["docker", "image", "inspect", tag]))[0]
        metadata["image_id"] = image["Id"]
        packages = {app: version}
        if app == "flamoris-generation-mcp":
            packages["flamoris-generation-controller"] = "1.0.0"
        check = "import importlib.metadata as m; " + "; ".join(
            f"assert m.version({name!r}) == {release!r}" for name, release in packages.items()
        )
        run(
            [
                "docker",
                "run",
                "--rm",
                "--network=none",
                "--entrypoint=python",
                image["Id"],
                "-c",
                check,
            ]
        )
        run(["docker", "save", "--output", str(output / "image.tar"), image["Id"]])
        if app == "flamoris-ai-agent":
            shutil.copytree(source / "db", output / "db")
    files = {}
    for file in sorted(output.rglob("*")):
        if file.is_file():
            h = hashlib.sha256()
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    h.update(chunk)
            files[str(file.relative_to(output))] = "sha256:" + h.hexdigest()
    metadata["files"] = files
    (output / "candidate.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
