"""Isolated release-role utility: validate payloads, then sign exact bytes. No publication."""

import argparse
from pathlib import Path

from flamoris_update_core.models import Manifest
from flamoris_update_core.wire import decode, dumps
from flamoris_updater_adapters.config import signer
from flamoris_updater_adapters.releases import Catalog, validate_notes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["release", "catalog"], required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--private-key", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--human-notes")
    parser.add_argument("--changes")
    args = parser.parse_args()
    raw = Path(args.input).read_bytes()
    payload = decode(Manifest if args.kind == "release" else Catalog, raw)
    if args.kind == "release":
        if not args.human_notes or not args.changes:
            raise SystemExit("Both bound release-note files are required")
        validate_notes(
            payload, Path(args.human_notes).read_bytes(), Path(args.changes).read_bytes()
        )
    output = Path(args.output)
    if output.exists():
        raise SystemExit("Refusing to replace a detached signature")
    output.write_bytes(dumps(signer(args.key_id, args.private_key).envelope(raw)) + b"\n")


if __name__ == "__main__":
    main()
