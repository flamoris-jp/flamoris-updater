"""Turn prebuilt candidates into portable Web/MCP/CLI installation recipes."""

import argparse
from pathlib import Path

from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.artifacts import origin, relative
from flamoris_updater_adapters.recipes import build_catalog
from flamoris_updater_adapters.self_update import SelfRelease


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="append",
        nargs=2,
        metavar=("CANDIDATE_JSON", "HTTPS_DIRECTORY"),
    )
    parser.add_argument(
        "--updater-bundle",
        action="append",
        nargs=2,
        metavar=("BUNDLE_DIGESTS_JSON", "HTTPS_DIRECTORY"),
    )
    parser.add_argument("--compatible-from", action="append", default=[])
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    if not args.candidate and not args.updater_bundle:
        parser.error("At least one application candidate or Updater bundle is required")
    catalog = build_catalog(
        [
            (loads(Path(filename).read_bytes()), location)
            for filename, location in args.candidate or []
        ]
    )
    releases = []
    for filename, location in args.updater_bundle or []:
        origin(location)
        metadata = loads(Path(filename).read_bytes())
        releases.append(
            SelfRelease.model_validate(
                {
                    "release": metadata["version"],
                    "compatible_from": args.compatible_from,
                    "artifact": {
                        "kind": "native",
                        "platform": metadata["platform"],
                        "locator": location.rstrip("/") + "/" + relative(metadata["artifact"]),
                        "digest": metadata["digest"],
                        "max_expanded_bytes": metadata["expanded_bytes"],
                        "content_index_digest": metadata["content_index_digest"],
                    },
                }
            )
        )
    catalog = type(catalog)(catalog_version=1, recipes=catalog.recipes, updater_releases=releases)
    Path(args.output).write_bytes(dumps(catalog) + b"\n")


if __name__ == "__main__":
    main()
