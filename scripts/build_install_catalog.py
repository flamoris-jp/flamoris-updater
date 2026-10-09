"""Turn prebuilt candidates into portable Web/MCP/CLI installation recipes."""

import argparse
from pathlib import Path

from flamoris_update_core.wire import dumps, loads
from flamoris_updater_adapters.recipes import build_catalog


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        action="append",
        nargs=2,
        metavar=("CANDIDATE_JSON", "HTTPS_DIRECTORY"),
        required=True,
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    catalog = build_catalog(
        [(loads(Path(filename).read_bytes()), origin) for filename, origin in args.candidate]
    )
    Path(args.output).write_bytes(dumps(catalog) + b"\n")


if __name__ == "__main__":
    main()
