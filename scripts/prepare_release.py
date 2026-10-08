"""Prepare one immutable multi-platform manifest from CI-verified bundle digests."""

import argparse
import importlib.metadata
from pathlib import Path

from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, digest, dumps, loads, version
from flamoris_updater_adapters.artifacts import origin


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundles", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--release-origin", required=True)
    args = parser.parse_args()
    version(args.version)
    origin(args.release_origin)
    if importlib.metadata.version("flamoris-updater") != args.version:
        raise SystemExit("Release and built package versions disagree")
    bundles = [loads(p.read_bytes()) for p in Path(args.bundles).rglob("bundle-digests.json")]
    if len(bundles) != 2 or {b["platform"] for b in bundles} != {"linux/amd64", "linux/arm64"}:
        raise SystemExit("Both verified platform bundles are required")
    root = Path(args.output)
    root.mkdir(parents=True, exist_ok=True)
    human = Path(f"release-notes/{args.version}.md").read_bytes()
    changes = Path(f"release-notes/{args.version}.changes.json").read_bytes()
    obj = loads(changes)
    if obj["release"] != args.version:
        raise SystemExit("Versioned release notes are required")
    artifacts = [
        {
            "kind": "native",
            "platform": b["platform"],
            "locator": args.release_origin.rstrip("/") + "/v" + args.version + "/" + b["artifact"],
            "digest": b["digest"],
            "max_expanded_bytes": b["expanded_bytes"],
            "content_index_digest": b["content_index_digest"],
        }
        for b in sorted(bundles, key=lambda b: b["platform"])
    ]
    raw = dumps(
        {
            "manifest_version": 1,
            "application_id": "flamoris-updater",
            "release": args.version,
            "source": {
                "repository": "flamoris-jp/flamoris-updater",
                "tag": "v" + args.version,
                "revision": args.revision,
            },
            "artifact": artifacts[0],
            "artifact_variants": artifacts[1:],
            "components": [],
            "interfaces": [],
            "dependencies": [],
            "schema_targets": {"control": "updater-control-1"},
            "migrations": [],
            "lifecycle_profile": {
                "id": "updater-controller-v1",
                "restart_required": True,
                "admission_gate_required": True,
                "validation_profiles": ["control-read-only-v1"],
            },
            "backup_profile": {"id": "preserve-control-v1", "resource_classes": ["control"]},
            "recovery": {
                "artifact_only": True,
                "data_restore": False,
                "previous_schema_constraints": {"control": ["updater-control-1"]},
            },
            "initialization": {"supported": False},
            "release_notes": {
                "human": {"locator": "release-notes.md", "digest": digest(human)},
                "changes": {"locator": "changes.json", "digest": digest(changes)},
            },
        }
    )
    decode(Manifest, raw)
    (root / "release.json").write_bytes(raw)
    (root / "release-notes.md").write_bytes(human)
    (root / "changes.json").write_bytes(changes)


if __name__ == "__main__":
    main()
